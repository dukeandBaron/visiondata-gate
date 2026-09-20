import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Database, RefreshCw, ShieldCheck } from 'lucide-react';
import { useProduct } from '../ProductContext';
import { getIdentitySessionSnapshot, subscribeIdentitySession } from '../identitySession';
import { listAgentTasks, getTaskVisualEvidence, OperatorApiError } from '../data/api';
import { getLearningReadiness } from '../data/learningApi';
import type { AgentTask } from '../agentDomain';
import type { LearningReadiness } from '../learningDomain';
import { poolMemberCanQualify, poolPendingStorageKey, readPoolPendingWrite, persistPoolPendingWrite, clearPoolPendingWrite, dataPoolDigest,
  type PoolPendingState, type PendingPoolWrite, type DataPoolProjection, type DataPoolDerivation, type PoolVersionProjection,
  type DataPoolScope, type CreateDataPoolRequest, type CreatePoolVersionRequest, type DeriveDataPoolRequest, type PoolDisposition, type PoolRepairAction, type PoolRepairResult } from '../dataPoolDomain';
import { listTaskDataPools, getDataPool, getDataPoolVersion, createDataPool, createDataPoolVersion, deriveDataPool, getDataPoolOperation, normalizeDataPoolRequest } from '../data/dataPoolApi';
import type { TaskVisualEvidenceManifest } from '../visualEvidenceDomain';
import '../styles/data-pools.css';

const short = (value: string) => value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-7)}` : value;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '读取失败，请恢复连接后重新读取。';
const readinessLabels: Record<LearningReadiness['members'][number]['readiness_state'], string> = {
  UNVERIFIED_FINDING_IDENTITY: '问题身份未映射 · HOLD',
  UNVERIFIED_TOOL_FAILURE: '检查工具失败 · HOLD',
  UNVERIFIED: '证据未核验 · HOLD',
  NEEDS_ATTENTION: '存在具体问题 · 等待复核',
  MASK_REQUIRED_FOR_REFERENCE_TRAINER: '参考训练器缺少掩膜 · 不代表坏数据',
  BLOCKED_BY_BATCH: '批次未通过 · 不推断本样本合格',
  GATE_ELIGIBLE_NOT_TRAINING_APPROVED: '满足检查交接条件 · 尚未训练审批',
};

export function DataPoolsPage() {
  const { activeWorkspace, activeProject, connection } = useProduct();
  const identity = useSyncExternalStore(subscribeIdentitySession, getIdentitySessionSnapshot);
  const workspaceId = activeWorkspace?.workspace_id, projectId = activeProject?.project_id;
  const scope = useMemo(() => workspaceId && projectId ? { workspaceId, projectId } : null, [workspaceId, projectId]);
  if (!identity.user || identity.user.status !== 'ACTIVE') return <section className="data-pools-page"><h1>数据池与返修版本</h1><p>请先登录已启用的账号；未登录不会读取项目数据。</p></section>;
  if (!scope || !activeProject) return <section className="data-pools-page"><h1>数据池与返修版本</h1><p>请先选择工作空间和项目。这里不会显示其他项目的数据池。</p></section>;
  return <PoolWorkbench key={`${identity.user.user_id}:${identity.generation}:${workspaceId}:${projectId}`}
    scope={scope} actorId={identity.user.user_id} projectName={activeProject.name} connected={connection.api === 'CONNECTED'} />;
}

function PoolWorkbench({ scope, actorId, projectName, connected }: { scope: DataPoolScope; actorId: string; projectName: string; connected: boolean }) {
  const [params, setParams] = useSearchParams();
  const selectedTaskId = params.get('task') ?? '';
  const selectedPoolId = params.get('pool') ?? '';
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [readiness, setReadiness] = useState<LearningReadiness | null>(null);
  const [visual,setVisual]=useState<TaskVisualEvidenceManifest|null>(null);
  const [pools,setPools]=useState<DataPoolProjection[]>([]),[pool,setPool]=useState<DataPoolProjection|null>(null);
  const [history,setHistory]=useState<PoolVersionProjection|null>(null),[derivation,setDerivation]=useState<DataPoolDerivation|null>(null);
  const [notice,setNotice]=useState('');
  const storageKey=poolPendingStorageKey(actorId,scope);
  const [pending,setPending]=useState<PoolPendingState>(()=>readPoolPendingWrite(localStorage,storageKey));
  const pendingRef=useRef(pending),writing=useRef(false);pendingRef.current=pending;
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [fresh, setFresh] = useState(false);
  const generation = useRef(0), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; }; }, []);
  useEffect(()=>{const changed=(event:StorageEvent)=>{if(event.key===storageKey||event.key===null){setPending(readPoolPendingWrite(localStorage,storageKey));setFresh(false);}};window.addEventListener('storage',changed);return()=>window.removeEventListener('storage',changed);},[storageKey]);
  const refresh = useCallback(async () => {
    const token = ++generation.current;
    setLoading(true); setFresh(false); setReadiness(null); setVisual(null);setHistory(null); setError('');
    try {
      if (!connected) throw new Error('本地 API 未连接，保留 HOLD。');
      const rows = await listAgentTasks(scope.workspaceId, scope.projectId);
      if (!Array.isArray(rows) || rows.some(row => row.workspace_id !== scope.workspaceId || row.project_id !== scope.projectId)
        || new Set(rows.map(row => row.task_id)).size !== rows.length) throw new Error('任务列表与当前项目不匹配，已拒绝显示。');
      const allowed = rows.filter(row => row.source_kind === 'local_authorized_directory' && row.source_id !== null && row.execution_status === 'COMPLETED');
      const selected = allowed.find(row => row.task_id === selectedTaskId);
      if (selectedTaskId && !selected) throw new Error('所选任务不是当前项目的已完成授权数据任务。请重新选择。');
      const projected = selected ? await getLearningReadiness(scope, selected.task_id) : null;
      const assets=selected?await getTaskVisualEvidence(selected.task_id):null;
      if(selected&&assets&&(assets.task_id!==selected.task_id||assets.workspace_id!==scope.workspaceId||assets.project_id!==scope.projectId||assets.source_id!==selected.source_id
        ||!projected||assets.items.length!==projected.members.length||new Set(assets.items.map(row=>row.sample_id)).size!==assets.items.length||projected.members.some(row=>!assets.items.some(item=>item.sample_id===row.sample_id))))throw new Error('冻结视觉身份与本次检查成员不一致，禁止提交。');
      const list=selected?await listTaskDataPools(scope,selected.task_id):[];
      const current=selectedPoolId?await getDataPool(scope,selectedPoolId):list[0]??null;
      let restoredDerivation:DataPoolDerivation|null=null;
      if(current?.read_status==='CURRENT'){
        const pointer=readPoolPendingWrite(localStorage,`${storageKey}:verified-derive:${current.current_version.version_id}`);
        if(pointer&&'corrupt'in pointer)throw new Error('已完成派生的读取标识损坏，停止派生写入并保留 HOLD。');
        if(pointer){
          if(pointer.operation!=='derive'||pointer.targetId!==current.current_version.version_id)throw new Error('派生读取标识不属于当前版本。');
          const result=await getDataPoolOperation(scope,'derive',pointer.requestKey,pointer.targetId);
          if(result.lookup_status!=='FOUND'||result.result_type!=='derivation'||!result.current_result)throw new Error('已记录派生暂时无法 GET 核验，保留 HOLD。');
          const derived=result.current_result as DataPoolDerivation;
          const expected=current.current_version.members.filter(row=>row.disposition==='QUALIFIED_CANDIDATE').map(row=>row.sample_id).sort();
          if(derived.pool_id!==current.pool.pool_id||derived.version_id!==current.current_version.version_id||derived.parent_source_id!==current.current_version.source_id
            ||JSON.stringify([...derived.qualified_sample_ids].sort())!==JSON.stringify(expected))throw new Error('派生回执与当前完整成员选择不匹配。');
          restoredDerivation=derived;
        }
      }
      if(selected&&projected&&(await getLearningReadiness(scope,selected.task_id)).receipt_sha256!==projected.receipt_sha256)throw new Error('读取期间检查证据已变化，请重新核验。');
      if (!mounted.current || token !== generation.current) return;
      setTasks(allowed); setReadiness(projected);setVisual(assets);setPools(list);setPool(current);setDerivation(restoredDerivation);setFresh(true);
    } catch (caught) {
      if (mounted.current && token === generation.current) { setTasks([]); setReadiness(null); setError(errorMessage(caught)); }
    } finally { if (mounted.current && token === generation.current) setLoading(false); }
  }, [connected, scope, selectedTaskId,selectedPoolId,storageKey]);
  useEffect(() => { void refresh(); }, [refresh]);
  const task = tasks.find(row => row.task_id === selectedTaskId);
  const selectTask = (id: string) => {
    generation.current++; setFresh(false); setReadiness(null);
    setParams(current => { const next = new URLSearchParams(current); id ? next.set('task', id) : next.delete('task'); return next; });
  };
  const finishReconciliation=async(lock:PendingPoolWrite)=>{
    const result=await getDataPoolOperation(scope,lock.operation,lock.requestKey,lock.targetId);
    if(!mounted.current)return false;
    if(result.lookup_status!=='FOUND'||result.execution_status!=='COMPLETED'){setNotice('GET 尚未找到原请求完成凭据；保留 HOLD，不重发写入。');return false;}
    if(result.result_type==='derivation'){
      const pointerKey=`${storageKey}:verified-derive:${lock.targetId}`;
      localStorage.setItem(pointerKey,JSON.stringify(lock));
      const stored=readPoolPendingWrite(localStorage,pointerKey);
      if(!stored||'corrupt'in stored||stored.requestKey!==lock.requestKey)throw new Error('派生读取标识保存失败，保留待对账锁。');
      setDerivation(result.current_result as DataPoolDerivation);
    }
    clearPoolPendingWrite(localStorage,storageKey,lock);setPending(null);pendingRef.current=null;
    if(result.result_type==='pool'||result.result_type==='version'){
      const poolId=result.result_type==='pool'?(result.current_result as DataPoolProjection).pool.pool_id:(result.current_result as PoolVersionProjection).version.pool_id;
      setParams(current=>{const next=new URLSearchParams(current);next.set('pool',poolId);return next;});
    }
    setNotice('已通过 GET 核验原请求结果；未重发写入。');return true;
  };
  const reconcile=async()=>{
    const lock=pendingRef.current;if(!lock||'corrupt'in lock||loading)return;
    setLoading(true);setFresh(false);setError('');
    try{if(await finishReconciliation(lock))await refresh();}catch(caught){if(mounted.current)setError(errorMessage(caught));}finally{if(mounted.current)setLoading(false);}
  };
  const execute=async(operation:PendingPoolWrite['operation'],targetId:string,raw:Record<string,unknown>,action:(value:CreateDataPoolRequest|CreatePoolVersionRequest|DeriveDataPoolRequest)=>Promise<unknown>)=>{
    if(!fresh||loading||writing.current||pendingRef.current)return;
    if(!navigator.locks){setError('当前浏览器无法保证多窗口写入互斥，操作未发送。');return;}
    await navigator.locks.request(`${storageKey}:writer`,{mode:'exclusive',ifAvailable:true},async ownership=>{
      if(!ownership){setError('另一窗口正在处理本项目写入，请稍后仅 GET 对账。');return;}
      const existing=readPoolPendingWrite(localStorage,storageKey);if(existing){setPending(existing);setFresh(false);return;}
      let lock:PendingPoolWrite|null=null,postAccepted=false;
      try{
        const request=normalizeDataPoolRequest(operation,{...raw,request_key:crypto.randomUUID()});
        lock={requestKey:request.request_key,operation,targetId,requestSha256:await dataPoolDigest(request)};
        if(!mounted.current)return;
        persistPoolPendingWrite(localStorage,storageKey,lock);pendingRef.current=lock;setPending(lock);writing.current=true;setLoading(true);setFresh(false);setError('');setNotice('');
        await action(request);postAccepted=true;if(!mounted.current)return;
        if(await finishReconciliation(lock))await refresh();
      }catch(caught){
        // A server evidence HOLD can occur after a bounded source copy was made.
        // Only local validation or authentication/schema rejection proves no dispatch.
        const refused=!postAccepted&&caught instanceof OperatorApiError
          &&(caught.code==='DATA_POOL_REQUEST_NOT_SENT'||[401,403,422].includes(caught.status))
          &&caught.code!=='DATA_POOL_CONTRACT_HOLD';
        if(refused&&lock){try{clearPoolPendingWrite(localStorage,storageKey,lock);pendingRef.current=null;if(mounted.current)setPending(null);}catch{/* Keep durable HOLD if clearing could not be verified. */}}
        if(mounted.current){setFresh(false);setError(errorMessage(caught));}
      }finally{writing.current=false;if(mounted.current)setLoading(false);}
    });
  };
  const saveReview=async(request:Omit<CreateDataPoolRequest,'request_key'>)=>{
    if(pool)await execute('version',pool.pool.pool_id,{...request,expected_pool_sha256:pool.pool.receipt_sha256,expected_parent_version_sha256:pool.current_version.receipt_sha256,source_task_id:selectedTaskId},value=>createDataPoolVersion(scope,pool.pool.pool_id,value as CreatePoolVersionRequest));
    else await execute('create',selectedTaskId,request,value=>createDataPool(scope,selectedTaskId,value as CreateDataPoolRequest));
  };
  const viewVersion=async(versionId:string)=>{const token=++generation.current;setLoading(true);try{const record=await getDataPoolVersion(scope,versionId);if(mounted.current&&token===generation.current){if(record.version.pool_id!==pool?.pool.pool_id)throw new Error('历史版本不属于当前数据池。');setHistory(record);}}catch(caught){if(mounted.current&&token===generation.current){setError(errorMessage(caught));setFresh(false);}}finally{if(mounted.current&&token===generation.current)setLoading(false);}};
  const canAct=fresh&&!loading&&!pending&&connected;
  return <div className="data-pools-page" aria-busy={loading}>
    <header className="data-pools-header"><div><span><Database size={14} /> {projectName} · 数据版本工作台</span><h1>数据池与返修版本</h1><p>逐样本复核去向，保留原始版本；返修后用新的检查结果说话。</p></div><button onClick={() => void(pending?reconcile():refresh())} disabled={loading||Boolean(pending&&'corrupt'in pending)}><RefreshCw size={15} />{pending?'仅 GET 对账':'刷新服务端事实'}</button></header>
    <div className="data-pools-boundary"><ShieldCheck size={17} /><p>“数据合格”是指定合同下的验收结果，不是“产品无缺陷”标签。原因和返修结果只是诊断记录，不能代替标注真值；本页不训练、不自动执行 worker，也不批准生产放行。</p></div>
    {error && <div role="alert" className="data-pools-alert"><strong>STALE_HOLD</strong><p>{error} 旧结果不再授权操作。</p></div>}
    {pending&&<div className="data-pools-alert" role="status"><strong>写入结果待对账</strong><p>{'corrupt'in pending?'本地待对账标识无法读取，禁止新写入。请由管理员核对请求记录；不能直接清除后重试。':`请求 ${pending.requestKey} · ${pending.operation}。本账号、本项目后续写入已锁定；关页、重新登录后仍保留，只能 GET 对账，不能自动重试。`}</p></div>}
    {notice&&<p role="status" className="data-pools-notice">{notice}</p>}
    <div className="data-pools-layout"><aside className="data-pools-index"><h2>当前来源的数据池</h2><p>审核版本保留完整成员；新数据任务必须重新逐项复核。</p>{pools.map(item=><button key={item.pool.pool_id} aria-pressed={pool?.pool.pool_id===item.pool.pool_id} onClick={()=>{setFresh(false);setParams(current=>{const next=new URLSearchParams(current);next.set('pool',item.pool.pool_id);return next;});}} disabled={loading}><strong>{short(item.pool.pool_id)}</strong><small>{item.pool.version_ids.length} 个审核版本 · {item.read_status}</small></button>)}<Link to="/workspace?purpose=annotation-rework">打开标注工作簿</Link><Link to="/capa">查看整改工单</Link><Link to="/learning">查看学习周期</Link></aside>
      <main className="data-pools-main"><section className="data-pools-panel"><header><div><h2>选择复核来源</h2><p>仅列出当前项目已完成的授权本地数据任务。选择任务不会自动指定成员去向。</p></div></header>
        <div className="data-pools-controls"><label>来源任务<select aria-label="数据池来源任务" value={selectedTaskId} onChange={event => selectTask(event.target.value)} disabled={loading}><option value="">请明确选择任务</option>{tasks.map(row => <option key={row.task_id} value={row.task_id}>{short(row.task_id)} · {row.final_decision ?? '未取得决定'} · {row.goal.slice(0, 60)}</option>)}</select></label>{task && <Link to={`/command-center?task=${encodeURIComponent(task.task_id)}`}>查看冻结检查证据</Link>}</div>
        {fresh && !tasks.length && <p>当前没有可复核来源。先导入图像、完成标注复核、冻结版本并执行检查。</p>}
      </section>
      {pool&&<PoolVersionPanel key={pool.pool.receipt_sha256} projection={pool} history={history} derivation={derivation} canAct={canAct&&pool.read_status==='CURRENT'&&(!history||history.version.version_id===pool.current_version.version_id)} onVersion={viewVersion}
        onDerive={request=>execute('derive',pool.current_version.version_id,{...request,expected_pool_sha256:pool.pool.receipt_sha256,expected_version_sha256:pool.current_version.receipt_sha256},value=>deriveDataPool(scope,pool.pool.pool_id,pool.current_version.version_id,value as DeriveDataPoolRequest))}/>}
      {readiness && task && <ReadinessPanel value={readiness} />}
      {readiness&&visual&&task&&<DataPoolReviewForm key={`${selectedTaskId}:${readiness.receipt_sha256}:${pool?.pool.current_version_id??'new'}`} readiness={readiness} visual={visual}
        canAct={canAct&&(!pool||pool.read_status==='CURRENT'||pool.pool.current_task_id!==selectedTaskId)} onSubmit={saveReview} createVersion={Boolean(pool)}/>}
      </main>
    </div>
  </div>;
}

function ReadinessPanel({ value }: { value: LearningReadiness }) {
  return <section className="data-pools-panel"><header><div><h2>当前冻结成员 · {value.members.length} 项</h2><p>以下是已核验的检查投影；没有命中问题不代表已人工复核，也不会被默认放入合格池。</p></div><span className="data-pools-state">{value.projection_status}</span></header>
    <div className="data-pools-statline">{(['train', 'val', 'test'] as const).map(split => <span key={split}><b>{value.members.filter(row => row.split === split).length}</b>{split === 'train' ? '训练用途' : split === 'val' ? '验证用途 · 不回灌' : '测试用途 · 不回灌'}</span>)}</div>
    {(value.blockers.length > 0 || value.global_findings.length > 0 || value.unmapped_finding_refs.length > 0) && <div className="data-pools-alert"><strong>批次约束仍需逐项处理</strong><p>全局问题、覆盖不足、身份不明或工具失败，不能通过把未命中的成员视为合格来消除。</p><ul>{value.blockers.map(code => <li key={code}>{code}</li>)}{value.global_findings.map(row => <li key={row.finding_id}>全局问题：{row.code}</li>)}{value.unmapped_finding_refs.map(row => <li key={row.finding_id}>身份未映射：{row.code}</li>)}</ul></div>}
    <div className="data-pools-table-wrap"><table><thead><tr><th>成员 / 当前工作副本</th><th>类别与用途</th><th>已有检查证据</th><th>标注要求</th></tr></thead><tbody>{value.members.map(row => <tr key={row.sample_id}><td><Link to={`/workspace?purpose=annotation-rework&asset=${encodeURIComponent(row.sample_id)}`}>{row.sample_id}</Link><small>修改副本不会改动本次冻结证据</small></td><td>{row.category}<small>{row.split}</small></td><td>{readinessLabels[row.readiness_state]}{row.finding_refs.map(finding => <small key={finding.finding_id}>{finding.code} · {finding.severity}</small>)}</td><td>{row.annotation_requirement}<small>{row.mask_available === true ? '存在绑定掩膜' : row.mask_available === false ? '没有绑定掩膜' : '掩膜绑定未核验'}</small></td></tr>)}</tbody></table></div>
    <details><summary>查看准备情况原始回执与摘要</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
  </section>;
}

function PoolVersionPanel({projection,history,derivation,canAct,onVersion,onDerive}:{
  projection:DataPoolProjection;history:PoolVersionProjection|null;derivation:DataPoolDerivation|null;canAct:boolean;
  onVersion:(versionId:string)=>Promise<void>;onDerive:(request:{review_note:string;operator_attests_reviewed:true})=>Promise<void>;
}) {
  const [note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false);
  const {pool,current_version:current}=projection,version=history?.version??current;
  const submit=(event:FormEvent)=>{event.preventDefault();if(canAct&&confirmed&&note.trim().length>=8)void onDerive({review_note:note.trim(),operator_attests_reviewed:true});};
  return <section className="data-pools-panel"><header><div><h2>已保存审核版本 · 第 {version.version_number} 版{history?' · 历史只读':''}</h2><p>保存的是完整成员的审核决定，不会覆盖父版本，也不会自动修改标注。</p></div><span className="data-pools-state">{history?.read_status??projection.read_status}</span></header>
    {(projection.read_status==='STALE_HOLD'||history?.read_status==='STALE_HOLD')&&<div className="data-pools-alert"><strong>版本证据已失效 · HOLD</strong><p>{[...projection.stale_reasons,...(history?.stale_reasons??[])].join('、')}。返修后请选择新冻结任务，重新提交完整成员审核；旧证据不能用于派生。</p></div>}
    <div className="data-pools-lineage"><div><small>原始来源 / 当前版本来源</small><code>{pool.origin_source_id} → {version.source_id}</code><Link to={`/command-center?task=${encodeURIComponent(version.source_task_id)}`}>查看该版本冻结任务</Link></div><div><small>父版本（永不覆盖）</small><code>{version.parent_version_id??'初始版本，无父版本'}</code><code>{version.parent_version_sha256??'—'}</code></div><div><small>本版本完整成员</small><code>{version.qualified_count} 合格候选 · {version.repair_count} 返修 · {version.hold_count} HOLD</code></div><div><small>审核人 / 当前版本 SHA</small><code>{version.human_review.reviewer_name} · {version.human_review.reviewed_by}</code><code>{version.receipt_sha256}</code></div></div>
    <div className="data-pools-actions">{pool.version_ids.map(id=><button type="button" key={id} onClick={()=>void onVersion(id)}>{id===current.version_id?'读取当前审核版本':`读取历史 ${short(id)}`}</button>)}</div>
    <div className="data-pools-table-wrap"><table><thead><tr><th>完整成员</th><th>用途 / 类别</th><th>审核去向</th><th>原因 / 动作 / 结果</th><th>图像与标注版本</th></tr></thead><tbody>{version.members.map(row=><tr key={row.sample_id}><td><Link to={`/workspace?purpose=annotation-rework&asset=${encodeURIComponent(row.sample_id)}`}>{row.sample_id}</Link></td><td>{row.split}<small>{row.category}</small></td><td>{dispositionLabels[row.disposition]}</td><td>{row.repair_cause_codes.join('、')||'没有已映射原因代码'}<small>{actionLabels[row.repair_action]} · {resultLabels[row.repair_result]}</small><small>{row.decision_note}</small></td><td><code title={row.asset_sha256}>{short(row.asset_sha256)}</code><small>标注 revision {row.annotation_revision}</small><code title={row.annotation_sha256}>{short(row.annotation_sha256)}</code></td></tr>)}</tbody></table></div>
    <p>验证和测试用途始终保留，不会自动移入训练。返修原因和结果是诊断元数据，不能直接成为标签；训练仍由独立审批入口验证完整数据集。</p>
    <div className="data-pools-actions"><Link to={`/models?tab=vision&pool=${encodeURIComponent(pool.pool_id)}&version=${encodeURIComponent(version.version_id)}`}>带当前审核版本进入模型中心</Link><small>模型中心会重新读取并核验当前池版本；本链接不授予训练或推理权限。</small></div>
    {!derivation&&<form onSubmit={submit}><fieldset disabled={!canAct||current.qualified_count===0}><h3>按当前审核版本派生合格候选</h3><p>仅选择本版本中明确复核的候选成员。真子集生成新授权来源后仍为 NOT_STARTED / HOLD；本页不创建、批准或启动 Gate。</p><label>具名派生说明（绑定当前登录账号）<textarea aria-label="数据池派生说明" value={note} onChange={event=>{setNote(event.target.value);setConfirmed(false);}} minLength={8} maxLength={2000} required/></label><label className="data-pools-check"><input type="checkbox" aria-label="确认数据池派生" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>以当前登录账号确认仅按此审核版本派生；禁止原图修改、标签推断、自动训练与生产放行。</label><button type="submit" disabled={!confirmed||note.trim().length<8}>派生已复核候选来源</button></fieldset></form>}
    {derivation&&<div className="data-pools-alert"><strong>{derivation.materialization_mode==='DERIVED_QUALIFIED_SUBSET'?'新来源已建立 · 新 Gate 尚未开始 · HOLD':'全部成员引用原快照 · 未制造新数据版本'}</strong><p>{derivation.qualified_sample_ids.length} 个明确候选；新检查状态 {derivation.new_gate_status}。派生回执不等于训练授权或问题关闭。</p>{derivation.derived_source_id?<Link to={`/command-center?source=${encodeURIComponent(derivation.derived_source_id)}&create=1`}>使用该新来源创建 Gate（仍需计划审批）</Link>:<Link to={`/command-center?task=${encodeURIComponent(derivation.source_task_id)}`}>查看原任务与冻结证据</Link>}<details><summary>派生回执与来源绑定</summary><pre>{JSON.stringify(derivation,null,2)}</pre></details></div>}
    <details><summary>完整版本回执</summary><pre>{JSON.stringify(history??projection,null,2)}</pre></details>
  </section>;
}

type ReviewDraft = { disposition: PoolDisposition | ''; action: PoolRepairAction | ''; result: PoolRepairResult | ''; note: string };
const dispositionLabels: Record<PoolDisposition, string> = { QUALIFIED_CANDIDATE: '合格候选 · 仍需派生验收', REPAIR_REQUIRED: '需要返修', UNVERIFIED_HOLD: '证据不足 · 保留 HOLD' };
const actionLabels: Record<PoolRepairAction, string> = { NONE: '无返修动作', RELABEL: '修订标注', RECAPTURE: '重新采集', REMOVE_OR_REPARTITION: '移除或重新规划用途（不在本页执行）', INVESTIGATE: '继续调查' };
const resultLabels: Record<PoolRepairResult, string> = { NOT_APPLICABLE: '无返修结果', PENDING: '待处理', EVIDENCE_LINKED_NOT_VERIFIED: '已登记返修证据 · 尚未复验' };

/** Kept separate from transport: this form cannot dispatch workers or train models. */
export function DataPoolReviewForm({ readiness, visual, canAct, onSubmit, createVersion = false }: {
  readiness: LearningReadiness; visual: TaskVisualEvidenceManifest; canAct: boolean;
  onSubmit: (request: Omit<CreateDataPoolRequest, 'request_key'>) => Promise<void>; createVersion?: boolean;
}) {
  const [drafts, setDrafts] = useState<Record<string, ReviewDraft>>({});
  const [reviewer, setReviewer] = useState(''), [note, setNote] = useState(''), [attested, setAttested] = useState(false);
  const draftFor = (id: string): ReviewDraft => drafts[id] ?? { disposition:'', action:'', result:'', note:'' };
  const update = (id: string, patch: Partial<ReviewDraft>) => { setAttested(false); setDrafts(current => ({...current,[id]:{...(current[id] ?? {disposition:'',action:'',result:'',note:''}),...patch}})); };
  const identitiesMatch = readiness.members.length > 0 && readiness.members.length === visual.items.length
    && new Set(visual.items.map(row=>row.sample_id)).size === visual.items.length
    && readiness.members.every(row=>visual.items.some(item=>item.sample_id===row.sample_id));
  const complete = identitiesMatch && readiness.members.every(row => {
    const draft = draftFor(row.sample_id);
    return draft.disposition && draft.action && draft.result && draft.note.trim().length >= 8
      && (draft.disposition !== 'QUALIFIED_CANDIDATE' || poolMemberCanQualify(readiness,row.sample_id,visual.items.find(item=>item.sample_id===row.sample_id)))
      && (draft.disposition !== 'REPAIR_REQUIRED' || (row.finding_refs.length>0&&draft.action !== 'NONE' && draft.result !== 'NOT_APPLICABLE'))
      && (draft.disposition !== 'UNVERIFIED_HOLD' || (draft.action === 'INVESTIGATE' && draft.result !== 'NOT_APPLICABLE'));
  });
  const submit = (event: FormEvent) => {
    event.preventDefault(); if (!canAct || !complete || !attested) return;
    void onSubmit({ expected_readiness_sha256:readiness.receipt_sha256,reviewer_name:reviewer.trim(),review_note:note.trim(),operator_attests_reviewed:true,
      members:readiness.members.map(row=>{
        const asset=visual.items.find(item=>item.sample_id===row.sample_id)!, draft=draftFor(row.sample_id);
        return {sample_id:row.sample_id,expected_asset_sha256:asset.source_sha256,expected_annotation_revision:asset.annotation_revision,
          expected_annotation_sha256:asset.annotation_document_sha256,disposition:draft.disposition as PoolDisposition,
          repair_action:draft.action as PoolRepairAction,repair_result:draft.result as PoolRepairResult,decision_note:draft.note.trim()};
      }),
    });
  };
  return <section className="data-pools-panel"><header><div><h2>{createVersion?'重新逐项复核 · 新审核版本':'逐样本明确去向'}</h2><p>必须覆盖本次冻结任务的全部成员。保存审核版本不修改图片或标注；有缺陷的产品图也可以是有效数据。</p></div></header>
    {!identitiesMatch&&<p role="alert">成员与冻结视觉清单不一致，禁止提交。</p>}
    <form onSubmit={submit}><fieldset disabled={!canAct||!identitiesMatch}>
      {readiness.members.map(row=>{const draft=draftFor(row.sample_id);return <article className="data-pools-review-row" key={row.sample_id}><header><div><strong>{row.sample_id}</strong><p>{row.category} · {row.split} · {readinessLabels[row.readiness_state]}</p></div><Link to={`/workspace?purpose=annotation-rework&asset=${encodeURIComponent(row.sample_id)}`}>打开工作副本</Link></header>
        <div className="data-pools-review-fields"><label>人工复核去向<select aria-label={`成员去向 ${row.sample_id}`} value={draft.disposition} onChange={event=>{const value=event.target.value as PoolDisposition|'';update(row.sample_id,{disposition:value,action:value==='QUALIFIED_CANDIDATE'?'NONE':value==='UNVERIFIED_HOLD'?'INVESTIGATE':'',result:value==='QUALIFIED_CANDIDATE'?'NOT_APPLICABLE':''});}} required><option value="">请逐项选择，不默认合格</option>{Object.entries(dispositionLabels).map(([value,label])=><option key={value} value={value} disabled={(value==='QUALIFIED_CANDIDATE'&&!poolMemberCanQualify(readiness,row.sample_id,visual.items.find(item=>item.sample_id===row.sample_id)))||(value==='REPAIR_REQUIRED'&&row.finding_refs.length===0)}>{label}</option>)}</select></label>
          <label>返修动作<select aria-label={`返修动作 ${row.sample_id}`} value={draft.action} onChange={event=>update(row.sample_id,{action:event.target.value as PoolRepairAction|''})} disabled={draft.disposition==='QUALIFIED_CANDIDATE'||draft.disposition==='UNVERIFIED_HOLD'} required><option value="">请明确动作</option>{Object.entries(actionLabels).map(([value,label])=><option key={value} value={value} disabled={draft.disposition==='REPAIR_REQUIRED'&&value==='NONE'}>{label}</option>)}</select></label>
          <label>返修记录状态<select aria-label={`返修结果 ${row.sample_id}`} value={draft.result} onChange={event=>update(row.sample_id,{result:event.target.value as PoolRepairResult|''})} disabled={draft.disposition==='QUALIFIED_CANDIDATE'} required><option value="">请明确当前结果</option>{Object.entries(resultLabels).map(([value,label])=><option key={value} value={value} disabled={Boolean(draft.disposition&&draft.disposition!=='QUALIFIED_CANDIDATE'&&value==='NOT_APPLICABLE')}>{label}</option>)}</select></label>
          <label>原因与处置说明（诊断记录）<textarea aria-label={`处置说明 ${row.sample_id}`} value={draft.note} onChange={event=>update(row.sample_id,{note:event.target.value})} minLength={8} maxLength={1000} required placeholder="说明依据、拟采取的动作或返修证据；不是新的标注标签。"/></label></div>
          {row.finding_refs.length>0&&<p>已映射原因：{row.finding_refs.map(item=>item.code).join('、')}。原因代码由服务端证据生成，文字记录不替代事实。</p>}
        </article>;})}
      <div className="data-pools-review-fields"><label>具名复核人<input aria-label="数据池复核人" value={reviewer} onChange={event=>{setReviewer(event.target.value);setAttested(false);}} minLength={2} maxLength={120} required/></label><label>整体审核说明<textarea aria-label="数据池审核说明" value={note} onChange={event=>{setNote(event.target.value);setAttested(false);}} minLength={8} maxLength={2000} required/></label></div>
      <label className="data-pools-check"><input type="checkbox" aria-label="确认逐成员数据池复核" checked={attested} onChange={event=>setAttested(event.target.checked)}/>我已逐项查看本次冻结证据并确认去向；原因和返修结果仅为诊断记录，不授予标注真值、训练或生产权限。</label>
      <div className="data-pools-actions"><button type="submit" className="data-pools-primary" disabled={!complete||!attested||reviewer.trim().length<2||note.trim().length<8}>{createVersion?'保存新的审核版本':'保存数据池审核版本'}</button><p>保存后必须 GET 对账；原始冻结版本始终保留。</p></div>
    </fieldset></form>
  </section>;
}
