import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Activity, Cpu, Database, FileCheck2, RefreshCw, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { useProduct } from '../ProductContext';
import { getIdentityActorId } from '../identitySession.ts';
import { getVisionCapabilities, listVisionRecords, getVisionRun, getVisionModel, getVisionInferenceAsset, getVisionInference, getVisionOperation, getVisionFeedback,
  getVisionPool, getVisionHeatmap, getNormalityFeedback, getNormalityFollowup, getNormalityFollowupAnnotations, getVisionTttCapabilities, prepareVisionMutation, sendVisionMutation, visionWriteKnownRejected, visionErrorMessage } from '../data/visionModelApi.ts';
import { parseDetectionManifest, parseVisionPending, visionPendingStorageKey, visionStatusLabel, visionEnsure } from '../visionModelDomain.ts';
import type { VisionScope, VisionPending, VisionMutationOperation, VisionRecord, VisionModel, VisionNormalityModel, VisionRuntime, VisionDataset, VisionRun,
  VisionInferenceAsset, VisionInference, VisionCapabilities, VisionApproval, VisionBudget, DetectionManifest, CreateVisionRunRequest, VisionFeedback,
  VisionFeedbackClassification, NormalityFeedback, NormalityFeedbackClassification, NormalityFollowupImport, NormalityFollowupWorkOrder, NormalityFollowupList, NormalityFollowupAnnotations, VisionTttCapabilities, VisionTttFailure, VisionTttBudget, VisionTttReport, RegisterNormalityModelPackRequest, ApproveNormalityModelPackRequest, RegisterVisionInferenceAssetRequest, RunNormalityInferenceRequest } from '../visionModelDomain.ts';
import type { DataPoolProjection } from '../dataPoolDomain.ts';
import '../styles/vision-models.css';

type Tab = 'runtime' | 'model' | 'dataset' | 'run' | 'normality';
type Execute = (operation: VisionMutationOperation, request: (key: string) => unknown, context?: { runId: string }) => Promise<boolean>;
interface ApprovalState { reviewer: string; note: string }
const tabs: { id: Tab; title: string; icon: typeof Cpu }[] = [
  { id: 'runtime', title: '运行环境', icon: Cpu }, { id: 'model', title: '权重', icon: FileCheck2 },
  { id: 'dataset', title: '数据', icon: Database }, { id: 'run', title: '训练', icon: SlidersHorizontal }, { id: 'normality', title: 'Normality 推理', icon: Activity },
];
const digestValid = (value: string) => /^[a-f0-9]{64}$/.test(value);
const approvalReady = (value: ApprovalState) => value.reviewer.trim().length >= 2 && value.note.trim().length >= 8;
function approval(value: ApprovalState, key: string): VisionApproval { return { request_key: key, reviewer_identity: value.reviewer.trim(), note: value.note.trim() }; }
function readPending(key: string): { pending: VisionPending | null; corrupt: boolean } {
  try { const raw = window.localStorage.getItem(key); return { pending: raw ? parseVisionPending(raw) : null, corrupt: false }; }
  catch { return { pending: null, corrupt: true }; }
}
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="vision-models__check"><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} /><span>{label}</span></label>;
}
function ApprovalFields({ value, onChange }: { value: ApprovalState; onChange: (value: ApprovalState) => void }) {
  return <div className="vision-models__approval"><label>具名复核人<input value={value.reviewer} minLength={2} maxLength={160} required autoComplete="off" onChange={e => onChange({ ...value, reviewer: e.target.value })} /></label>
    <label>本次操作说明<textarea value={value.note} minLength={8} maxLength={1000} required rows={2} onChange={e => onChange({ ...value, note: e.target.value })} /></label>
    <small>姓名是复核声明；访问权限仍由当前登录账号决定。请勿填写路径、密钥或原始数据内容。</small></div>;
}
function Sha({ label, value }: { label: string; value: string }) { return <div className="vision-models__sha"><span>{label}</span><code>{value}</code></div>; }
function Empty({ children }: { children: ReactNode }) { return <p className="vision-models__empty">{children}</p>; }
function isFollowupRecord(record: VisionRecord): record is NormalityFollowupImport | NormalityFollowupWorkOrder { return record.schema_version === 'visiondata-gate.normality-followup-import.v1' || record.schema_version === 'visiondata-gate.normality-followup-work-order.v1'; }

export function VisionModelWorkbench() {
  const { activeProject, activeWorkspace } = useProduct();
  const actorId = getIdentityActorId();
  const scope = useMemo(() => activeProject && activeWorkspace && actorId ? { projectId: activeProject.project_id, workspaceId: activeWorkspace.workspace_id, actorId } : null,
    [activeProject?.project_id, activeWorkspace?.workspace_id, actorId]);
  if (!scope || !activeProject) return <section className="vision-models"><h2>本地视觉模型</h2><Empty>请登录并选择工作空间和项目；本页不使用匿名演示模型。</Empty></section>;
  return <ScopedVisionWorkbench key={`${scope.actorId}:${scope.workspaceId}:${scope.projectId}`} scope={scope} projectName={activeProject.name} />;
}
export default VisionModelWorkbench;

function ScopedVisionWorkbench({ scope, projectName }: { scope: VisionScope; projectName: string }) {
  const { registerScopeChangeGuard } = useProduct();
  const [params] = useSearchParams(); const poolId = params.get('pool');
  const [tab, setTab] = useState<Tab>(poolId ? 'dataset' : 'runtime');
  const [capabilities, setCapabilities] = useState<VisionCapabilities>();
  const [models, setModels] = useState<VisionModel[]>([]), [runtimes, setRuntimes] = useState<VisionRuntime[]>([]);
  const [datasets, setDatasets] = useState<VisionDataset[]>([]), [runs, setRuns] = useState<VisionRun[]>([]);
  const [inferenceAssets, setInferenceAssets] = useState<VisionInferenceAsset[]>([]), [inferences, setInferences] = useState<VisionInference[]>([]);
  const [feedback, setFeedback] = useState<VisionFeedback[]>([]);
  const [feedbackRevision, setFeedbackRevision] = useState(0);
  const [tttFailures, setTttFailures] = useState<VisionTttFailure[]>([]);
  const [selected, setSelected] = useState<VisionRecord>(); const selectedRef = useRef<VisionRecord | undefined>(undefined); selectedRef.current = selected;
  const storageKey = visionPendingStorageKey(scope);
  const [lock, setLock] = useState(() => readPending(storageKey)); const lockRef = useRef(lock); lockRef.current = lock;
  const [fresh, setFresh] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const mounted = useRef(true), writing = useRef(false), reading = useRef(false);
  const validScope = useCallback(() => mounted.current && getIdentityActorId() === scope.actorId, [scope.actorId]);
  const clearLock = useCallback((pending: VisionPending) => {
    const current = readPending(storageKey);
    if (!current.corrupt && current.pending?.operation === pending.operation && current.pending.requestKey === pending.requestKey) {
      window.localStorage.removeItem(storageKey); lockRef.current = { pending: null, corrupt: false };
      if (validScope()) setLock(lockRef.current);
    }
  }, [storageKey, validScope]);
  const refresh = useCallback(async () => {
    if (reading.current || writing.current || !validScope()) return;
    reading.current = true; setBusy(true); setFresh(false); setError('');
    try {
      const [c, m, r, d, tr, assets, results] = await Promise.all([getVisionCapabilities(scope), listVisionRecords(scope, 'model'), listVisionRecords(scope, 'runtime'),
        listVisionRecords(scope, 'dataset'), listVisionRecords(scope, 'run'), listVisionRecords(scope, 'inference_asset'), listVisionRecords(scope, 'inference')]);
      const failures = c.ttt_status === 'NORMALITY_EPISODIC_AVAILABLE' ? await listVisionRecords(scope, 'ttt_failure') : [];
      if (!validScope()) return;
      // Counts are advisory; concurrent training may add a candidate between GETs.
      setCapabilities(c); setModels(m); setRuntimes(r); setDatasets(d); setRuns(tr); setInferenceAssets(assets); setInferences(results); setTttFailures(failures);
      const chosen = selectedRef.current;
      if (chosen) setSelected([...m, ...r, ...d, ...tr, ...assets, ...results, ...failures].find(item => item.resource_id === chosen.resource_id));
      setFresh(true);
    } catch (failure) { if (validScope()) { setError(visionErrorMessage(failure)); setCapabilities(undefined); } }
    finally { reading.current = false; if (validScope()) setBusy(false); }
  }, [scope, validScope]);
  useEffect(() => {
    mounted.current = true; void refresh();
    const onStorage = (event: StorageEvent) => { if (event.key === storageKey || event.key === null) { const next = readPending(storageKey); lockRef.current = next; setLock(next); setFresh(false); } };
    window.addEventListener('storage', onStorage);
    return () => { mounted.current = false; window.removeEventListener('storage', onStorage); };
  }, [refresh, storageKey]);
  useEffect(() => registerScopeChangeGuard(() => !writing.current), [registerScopeChangeGuard]);
  const readFollowupBinding = async (row: NormalityFollowupImport | NormalityFollowupWorkOrder) => {
    const inference = await getVisionInference(scope, row.inference_id), feedback = (await getNormalityFeedback(scope, inference)).find(item => item.feedback_id === row.feedback_id && item.receipt_sha256 === row.feedback_sha256);
    visionEnsure(feedback); const persisted = await getNormalityFollowup(scope, feedback);
    visionEnsure([...persisted.imports, ...persisted.work_orders].some(item => item.resource_id === row.resource_id && item.receipt_sha256 === row.receipt_sha256)); return inference;
  };
  const executeOwned: Execute = async (operation, build, context) => {
    if (!validScope() || writing.current || reading.current || !fresh || lockRef.current.pending || lockRef.current.corrupt) return false;
    writing.current = true; setBusy(true); setError(''); setNotice('');
    let pending: VisionPending | undefined;
    let success = false;
    try {
      const prepared = await prepareVisionMutation(scope, operation, build(`vision_${crypto.randomUUID().replaceAll('-', '')}`), context);
      if (!validScope()) return false;
      // Store only operation + request key. Paths, JSON manifests, notes and credentials never enter storage.
      const existing = readPending(storageKey);
      if (existing.corrupt || existing.pending) { lockRef.current = existing; setLock(existing); setFresh(false); setError('HOLD：已有待对账操作，未发送新请求。'); return false; }
      pending = prepared.pending;
      try { window.localStorage.setItem(storageKey, JSON.stringify(pending)); }
      catch { setLock({ pending: null, corrupt: true }); lockRef.current = { pending: null, corrupt: true }; setError('HOLD：无法保存最小对账标识；操作未发送。'); return false; }
      lockRef.current = { pending, corrupt: false }; setLock(lockRef.current);
      const result = await sendVisionMutation(prepared);
      let reviewedInference: VisionInference | undefined;
      if (result.schema_version === 'visiondata-gate.normality-feedback.v1') {
        const item = result as NormalityFeedback; reviewedInference = await getVisionInference(scope, item.inference_id);
        const persisted = await getNormalityFeedback(scope, reviewedInference);
        visionEnsure(persisted.some(row => row.feedback_id === item.feedback_id && row.receipt_sha256 === item.receipt_sha256));
      }
      if (isFollowupRecord(result)) reviewedInference = await readFollowupBinding(result);
      clearLock(pending); success = true;
      if (validScope()) {
        if (reviewedInference) { setSelected(reviewedInference); setFeedbackRevision(value => value + 1); }
        else if (result.schema_version === 'visiondata-gate.vision-feedback.v1') { const item = result as VisionFeedback; setFeedback(current => [...current.filter(row => row.feedback_id !== item.feedback_id), item]); }
        else setSelected(result);
        setNotice('操作已收到完整性验证回执。请依据实际状态复核，不代表精度通过或生产放行。'); setFresh(false);
      }
    } catch (failure) {
      if (pending && visionWriteKnownRejected(failure)) clearLock(pending);
      if (validScope()) { setError(visionErrorMessage(failure)); setFresh(false); }
    } finally {
      writing.current = false; if (validScope()) setBusy(false);
    }
    if (success) await refresh();
    return success;
  };
  const execute: Execute = async (operation, build, context) => {
    // Web Locks serializes the same account/project across tabs; storage retains UNKNOWN after the tab is gone.
    if (!navigator.locks) { setError('HOLD：当前浏览器不支持跨页写入互斥；请使用本机现代浏览器，操作未发送。'); return false; }
    return navigator.locks.request(storageKey, { ifAvailable: true }, async acquired => {
      if (!acquired) { if (validScope()) setError('HOLD：同一账号与项目的另一个页面正在写入；本页未发送。'); return false; }
      return executeOwned(operation, build, context);
    });
  };
  const reconcile = async () => {
    const pending = lockRef.current.pending;
    if (!pending || busy || writing.current || !validScope()) return;
    setBusy(true); setError(''); setFresh(false); reading.current = true;
    let confirmed = false;
    try {
      const receipt = await getVisionOperation(scope, pending);
      if (!validScope()) return;
      if (isFollowupRecord(receipt.resource)) {
        const inference = await readFollowupBinding(receipt.resource); if (!validScope()) return; setSelected(inference); setFeedbackRevision(value => value + 1);
      } else if (receipt.resource.schema_version === 'visiondata-gate.normality-feedback.v1') {
        const item = receipt.resource as NormalityFeedback, inference = await getVisionInference(scope, item.inference_id);
        const persisted = await getNormalityFeedback(scope, inference);
        visionEnsure(persisted.some(row => row.feedback_id === item.feedback_id && row.receipt_sha256 === item.receipt_sha256));
        if (!validScope()) return; setSelected(inference); setFeedbackRevision(value => value + 1);
      } else if (receipt.resource.schema_version === 'visiondata-gate.vision-feedback.v1') {
        const item = receipt.resource as VisionFeedback; setFeedback(current => [...current.filter(row => row.feedback_id !== item.feedback_id), item]);
        setSelected(await getVisionRun(scope, item.run_id));
      } else setSelected(receipt.resource);
      clearLock(pending);
      confirmed = true;
      setNotice('原请求已由 GET 对账确认。没有重发 POST，也没有重新训练。');
    } catch (failure) { if (validScope()) setError(`原操作尚未得到可验证回执，锁仍保留。${visionErrorMessage(failure)}`); }
    finally { reading.current = false; if (validScope()) setBusy(false); }
    if (confirmed) await refresh();
  };
  const details = async (record: VisionRecord) => {
    if (busy || !validScope()) return;
    setBusy(true); setError('');
    try {
      const next = 'failure_id' in record ? record : 'inference_id' in record ? await getVisionInference(scope, record.inference_id) : 'asset_id' in record ? await getVisionInferenceAsset(scope, record.asset_id)
        : 'run_id' in record ? await getVisionRun(scope, record.run_id) : 'model_id' in record ? await getVisionModel(scope, record.model_id) : record;
      if (validScope()) setSelected(next);
    } catch (failure) { if (validScope()) { setFresh(false); setError(visionErrorMessage(failure)); } }
    finally { if (validScope()) setBusy(false); }
  };
  const canAct = fresh && Boolean(capabilities) && !busy && !lock.pending && !lock.corrupt;
  const normalityModels = models.filter((item): item is VisionNormalityModel => item.task_type === 'normality');
  const records: VisionRecord[] = tab === 'normality' ? [...normalityModels, ...inferenceAssets, ...inferences, ...tttFailures] : { runtime: runtimes, model: models.filter(item => item.task_type !== 'normality'), dataset: datasets, run: runs }[tab];
  return <section className="vision-models" aria-label="本地视觉模型工作台">
    <header className="vision-models__header"><div><p>LOCAL VISION / {projectName}</p><h2>把模型放进可复核的训练流程</h2><span>权重、数据与运行环境各自绑定 SHA-256。每次执行都需要独立授权。</span></div>
      <button type="button" onClick={() => void refresh()} disabled={busy}><RefreshCw size={15} />刷新状态（仅 GET）</button></header>
    <div className="vision-models__boundary"><ShieldCheck size={18} /><p><strong>当前执行边界：本地 CPU · detect 训练 + Normality 沙箱推理</strong><span>不自动下载权重、不外发数据；GPU 未运行；{capabilities?.ttt_status === 'NORMALITY_EPISODIC_AVAILABLE' ? 'Normality 单次 TTT 可单独授权；不持久学习；detect TTT 关闭' : 'TTT 关闭（未实现）'}；远程算力 CONNECTOR_NOT_CONFIGURED；工业效果 NOT_EVALUATED；不接生产。</span></p></div>
    {error && <div className="vision-models__alert" role="alert">{error}</div>}
    {notice && <div className="vision-models__notice" role="status">{notice}</div>}
    {lock.corrupt && <div className="vision-models__alert" role="alert">HOLD：本浏览器对账锁无法读取或存储不可用。所有写入已阻止；请先通过服务端操作记录核查，不要通过清除锁来重跑训练。</div>}
    {lock.pending && <div className="vision-models__alert" role="status"><strong>写入结果待确认 · UNKNOWN</strong><p>只保存当前账号与项目的操作名和请求标识。关页后保留，不保存路径、复核说明或令牌。</p><code>{lock.pending.operation} · {lock.pending.requestKey}</code>
      <button type="button" onClick={() => void reconcile()} disabled={busy}>使用原 request_key 仅 GET 对账</button></div>}
    <nav className="vision-models__tabs" aria-label="视觉模型流程">{tabs.map(({ id, title, icon: Icon }) => <button type="button" key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => { setTab(id); setSelected(undefined); }}><Icon size={16} />{title}<span>{id === 'normality' ? normalityModels.length + inferenceAssets.length + inferences.length + tttFailures.length : ({ runtime: runtimes, model: models.filter(item => item.task_type !== 'normality'), dataset: datasets, run: runs }[id]).length}</span></button>)}</nav>
    <div className="vision-models__layout"><div className="vision-models__form-panel">
      {tab === 'runtime' && <RuntimeForm canAct={canAct} execute={execute} />}
      {tab === 'model' && <ModelForm canAct={canAct} execute={execute} />}
      {tab === 'dataset' && <>{poolId ? <><PoolDatasetForm key={`${poolId}:${params.get('version') ?? ''}`} scope={scope} poolId={poolId} expectedVersionId={params.get('version')} canAct={canAct} execute={execute} />
        <details className="vision-models__external"><summary>也可登记外部检测 JSON 清单</summary><DatasetForm canAct={canAct} execute={execute} /></details></> : <DatasetForm canAct={canAct} execute={execute} />}</>}
      {tab === 'run' && <TrainingForm canAct={canAct} execute={execute} runtimes={runtimes} datasets={datasets} models={models.filter(item => item.task_type !== 'normality')} feedback={feedback} activeRun={runs.some(run => ['QUEUED', 'RUNNING'].includes(run.status))} />}
      {tab === 'normality' && <NormalityWorkbench scope={scope} tttAvailable={capabilities?.ttt_status === 'NORMALITY_EPISODIC_AVAILABLE'} canAct={canAct} execute={execute} models={normalityModels} runtimes={runtimes} assets={inferenceAssets} />}
    </div><div className="vision-models__records"><h3>{tabs.find(item => item.id === tab)?.title}记录</h3>
      {!records.length && <Empty>{fresh ? '当前项目还没有记录。登记完成后才能在下一阶段选择。' : '尚未读取到可验证记录；不会显示虚构样例。'}</Empty>}
      {records.map(record => <button className="vision-models__record" type="button" key={record.resource_id} disabled={busy} onClick={() => void details(record)} aria-pressed={selected?.resource_id === record.resource_id}>
        <strong>{'image_score' in record ? `${record.predicted_anomaly ? '异常信号' : '未越阈值'} · ${record.image_score.toFixed(4)}` : 'display_name' in record ? record.display_name : 'training' in record ? visionStatusLabel(record.status) : 'dataset_receipt' in record ? record.dataset_receipt.source_version : record.resource_id}</strong>
        <code>{record.resource_id}</code><span>{record.status}</span>{'runtime_id' in record && 'probe' in record && <small>库导入：{record.probe.status === 'failed' ? '失败 · metadata NOT_MEASURED' : record.probe.import_status}</small>}
      </button>)}
      {selected && ('failure_id' in selected ? <TttFailureDetails failure={selected} /> : ('inference_id' in selected) || ('asset_id' in selected) || ('task_type' in selected && selected.task_type === 'normality')
        ? <NormalityRecordDetails key={`${selected.receipt_sha256}:${feedbackRevision}`} scope={scope} record={selected as VisionNormalityModel | VisionInferenceAsset | VisionInference} canAct={canAct} execute={execute} runtimes={runtimes} />
        : <RecordDetails key={selected.receipt_sha256} record={selected} scope={scope} canAct={canAct} execute={execute} feedback={feedback} onFeedback={(runId, items) => setFeedback(current => [...current.filter(row => row.run_id !== runId), ...items])} />)}
    </div></div>
  </section>;
}

function RuntimeForm({ canAct, execute }: { canAct: boolean; execute: Execute }) {
  const [name, setName] = useState(''), [path, setPath] = useState(''), [sha, setSha] = useState('');
  const [trusted, setTrusted] = useState(false), [authorized, setAuthorized] = useState(false);
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' });
  return <form onSubmit={event => { event.preventDefault(); void execute('register_runtime', key => ({ ...approval(review, key), display_name: name.trim(), executable_path: path.trim(), expected_executable_sha256: sha, operator_attests_trusted_runtime: trusted, operator_attests_execution_authorized: authorized })).then(ok => { if (ok) { setPath(''); setTrusted(false); setAuthorized(false); } }); }}>
    <h3>登记外部 Python 环境</h3><p>执行指定解释器的标准库 metadata 探测；不会安装依赖或修改核心运行环境。登记后的实际库导入探测需再次授权。</p>
    <fieldset disabled={!canAct}><label>环境名称<input value={name} onChange={e => setName(e.target.value)} maxLength={120} required /></label>
      <label>Python 解释器绝对路径<input value={path} onChange={e => { setPath(e.target.value); setTrusted(false); setAuthorized(false); }} autoComplete="off" spellCheck={false} maxLength={2048} required /></label>
      <label>解释器 SHA-256<input value={sha} onChange={e => setSha(e.target.value.trim())} pattern="[a-f0-9]{64}" maxLength={64} required autoComplete="off" spellCheck={false} /></label>
      <small>路径只发送给本机后端，不进入浏览器存储或正常回执。请从可信文件清单取得 SHA-256。</small>
      <ApprovalFields value={review} onChange={setReview} />
      <Check label="我确认该解释器来自可信的本地环境。" checked={trusted} onChange={setTrusted} />
      <Check label="我授权本次执行该解释器，读取已安装包的元数据。" checked={authorized} onChange={setAuthorized} />
      <button type="submit" disabled={!name.trim() || !path.trim() || !digestValid(sha) || !trusted || !authorized || !approvalReady(review)}>登记并探测环境元数据</button>
    </fieldset></form>;
}

function ModelForm({ canAct, execute }: { canAct: boolean; execute: Execute }) {
  const [name, setName] = useState(''), [path, setPath] = useState(''), [sha, setSha] = useState(''), [source, setSource] = useState('');
  const [task, setTask] = useState<'detect' | 'segment'>('detect'), [license, setLicense] = useState('AGPL-3.0');
  const [read, setRead] = useState(false), [licenseAcknowledged, setLicenseAcknowledged] = useState(false);
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' });
  return <form onSubmit={event => { event.preventDefault(); if (!licenseAcknowledged) return; void execute('register_model', key => ({ ...approval(review, key), display_name: name.trim(), weights_path: path.trim(), expected_weights_sha256: sha, task_type: task, license_id: license, source_description: source.trim(), operator_attests_read_authorized: read })).then(ok => { if (ok) { setPath(''); setRead(false); setLicenseAcknowledged(false); } }); }}>
    <h3>登记已有本地权重</h3><p>只读取文件并核验 SHA，不下载、不加载，也不反序列化 .pt。登记不证明检测效果或预训练来源。</p>
    <fieldset disabled={!canAct}><label>模型名称<input value={name} onChange={e => setName(e.target.value)} maxLength={120} required /></label>
      <label>权重绝对路径<input value={path} onChange={e => { setPath(e.target.value); setRead(false); }} autoComplete="off" spellCheck={false} maxLength={2048} required /></label>
      <label>权重 SHA-256<input value={sha} onChange={e => setSha(e.target.value.trim())} maxLength={64} pattern="[a-f0-9]{64}" required spellCheck={false} /></label>
      <div className="vision-models__fields"><label>任务类型<select value={task} onChange={e => setTask(e.target.value as 'detect' | 'segment')}><option value="detect">检测框 detect</option><option value="segment">实例分割 segment（仅登记）</option></select></label>
        <label>许可声明<select value={license} onChange={e => { setLicense(e.target.value); setLicenseAcknowledged(false); }}><option value="AGPL-3.0">AGPL-3.0</option><option value="Enterprise">Enterprise（自行核验授权）</option></select></label></div>
      <label>来源说明（不填本地路径）<textarea value={source} onChange={e => setSource(e.target.value)} minLength={4} maxLength={500} required rows={2} /></label>
      {task === 'segment' && <p className="vision-models__inline-hold">HOLD：当前执行器只支持 CPU detect；segment 可以登记，不能在本页启动训练。</p>}
      <ApprovalFields value={review} onChange={setReview} />
      <Check label="我授权本次读取该本地权重文件并核验摘要。" checked={read} onChange={setRead} />
      <Check label="我已核查 AGPL-3.0 / Enterprise 的适用性；此声明不替代法律审查，分进程运行不会自动免除许可义务。" checked={licenseAcknowledged} onChange={setLicenseAcknowledged} />
      <button type="submit" disabled={!name.trim() || !path.trim() || !digestValid(sha) || source.trim().length < 4 || !read || !licenseAcknowledged || !approvalReady(review)}>只登记权重元数据</button>
  </fieldset></form>;
}

function NormalityWorkbench({ scope, tttAvailable, canAct, execute, models, runtimes, assets }: { scope: VisionScope; tttAvailable: boolean; canAct: boolean; execute: Execute; models: VisionNormalityModel[]; runtimes: VisionRuntime[]; assets: VisionInferenceAsset[] }) {
  const approved = models.filter(model => model.status === 'APPROVE_SANDBOX' && model.usage_scope === 'LOCAL_SANDBOX_ONLY');
  const [ttt, setTtt] = useState<VisionTttCapabilities>(), [error, setError] = useState(''), [loading, setLoading] = useState(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const readTtt = async () => { if (loading) return; setLoading(true); setTtt(undefined); setError('');
    try { const result = await getVisionTttCapabilities(scope); if (alive.current && getIdentityActorId() === scope.actorId) setTtt(result); }
    catch (failure) { if (alive.current) setError(visionErrorMessage(failure)); } finally { if (alive.current) setLoading(false); } };
  return <div className="vision-models__normality-workbench">
    <div className="vision-models__inline-hold"><strong>本机证据边界</strong><p>这里只执行已登记、已核验并由人工批准的 Normality 模型包。推理是模型信号，不是标签真值、Gate 决策或生产放行。</p><small>远程训练 / moxin：PREPARED_NOT_SUBMITTED · CONNECTOR_NOT_CONFIGURED。本页没有远程提交按钮。</small></div>
    {approved.length === 0 && <p className="vision-models__inline-hold">HOLD：当前项目没有已批准的 Normality 模型包。可以先登记 pack，再由具名人员单独批准沙箱执行。</p>}
    <details className="vision-models__external" open={models.length === 0}><summary>1 · 登记 Normality 模型包与冻结证据</summary><NormalityPackForm canAct={canAct} execute={execute} /></details>
    <details className="vision-models__external" open={assets.length === 0}><summary>2 · 登记本地推理输入图像</summary><NormalityAssetForm canAct={canAct} execute={execute} /></details>
    <NormalityInferenceForm canAct={canAct} execute={execute} models={approved} assets={assets} runtimes={runtimes} />
    {tttAvailable && <section aria-label="独立 TTT 授权"><h3>4 · 单次 TTT（独立授权）</h3><p>只更新本次学生副本；以独立人工 guard 检查遗忘，退化就回滚。不会更新原模型包，也不会持续学习。</p>
      <button type="button" disabled={loading} onClick={() => void readTtt()}>读取 TTT 能力（仅 GET）</button>{error && <p role="alert">{error}</p>}
      {ttt && <NormalityInferenceForm key={ttt.receipt_sha256} ttt={ttt} canAct={canAct} execute={execute} models={approved} assets={assets} runtimes={runtimes} />}</section>}
  </div>;
}

function NormalityPackForm({ canAct, execute }: { canAct: boolean; execute: Execute }) {
  const [name, setName] = useState(''); const [packPath, setPackPath] = useState(''), [packSha, setPackSha] = useState('');
  const [runDirectory, setRunDirectory] = useState(''), [stabilityDirectories, setStabilityDirectories] = useState(['', '', '']);
  const [summaryPath, setSummaryPath] = useState(''), [summarySha, setSummarySha] = useState('');
  const [bindingPath, setBindingPath] = useState(''), [bindingFileSha, setBindingFileSha] = useState(''), [bindingSha, setBindingSha] = useState('');
  const [indexPath, setIndexPath] = useState(''), [indexFileSha, setIndexFileSha] = useState(''), [indexSha, setIndexSha] = useState('');
  const [backbonePath, setBackbonePath] = useState(''), [backboneSha, setBackboneSha] = useState('');
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' });
  const [readAuthorized, setReadAuthorized] = useState(false), [weightsOnly, setWeightsOnly] = useState(false), [license, setLicense] = useState(false);
  const paths = [packPath, runDirectory, ...stabilityDirectories, summaryPath, bindingPath, indexPath, backbonePath];
  const digests = [packSha, summarySha, bindingFileSha, bindingSha, indexFileSha, indexSha, backboneSha];
  const ready = name.trim() && paths.every(value => value.trim()) && new Set(stabilityDirectories.map(value => value.trim())).size === 3
    && stabilityDirectories.map(value => value.trim()).includes(runDirectory.trim()) && digests.every(digestValid) && readAuthorized && weightsOnly && license && approvalReady(review);
  const setStability = (index: number, value: string) => setStabilityDirectories(current => current.map((item, itemIndex) => itemIndex === index ? value : item));
  return <form className="vision-models__normality-pack" onSubmit={event => { event.preventDefault(); if (!ready) return;
    void execute('register_normality_model_pack', key => ({ ...approval(review, key), display_name: name.trim(), model_pack_path: packPath.trim(), expected_model_pack_sha256: packSha,
      run_directory: runDirectory.trim(), stability_run_directories: stabilityDirectories.map(value => value.trim()), target_model_seed: 20260913,
      stability_summary_path: summaryPath.trim(), expected_stability_summary_sha256: summarySha, source_binding_path: bindingPath.trim(), expected_source_binding_file_sha256: bindingFileSha,
      expected_source_binding_sha256: bindingSha, source_index_path: indexPath.trim(), expected_source_index_file_sha256: indexFileSha, expected_source_index_sha256: indexSha,
      backbone_weights_path: backbonePath.trim(), expected_backbone_weights_sha256: backboneSha, operator_attests_read_authorized: readAuthorized,
      operator_attests_weights_only_load_authorized: weightsOnly, ultralytics_license_acknowledged: license } as RegisterNormalityModelPackRequest)).then(ok => { if (ok) { setReadAuthorized(false); setWeightsOnly(false); setLicense(false); } }); }}>
    <h3>登记模型包</h3><p>后端核验三次稳定性运行、来源绑定、索引、Backbone 和 pack 摘要。登记阶段不加载模型，也不代表沙箱批准。</p>
    <fieldset disabled={!canAct}><label>模型包名称<input aria-label="模型包名称" value={name} onChange={event => setName(event.target.value)} maxLength={120} required /></label>
      <label>模型包绝对路径<input aria-label="模型包绝对路径" value={packPath} onChange={event => { setPackPath(event.target.value); setReadAuthorized(false); }} required autoComplete="off" /></label>
      <label>模型包 SHA-256<input aria-label="模型包 SHA-256" value={packSha} onChange={event => setPackSha(event.target.value.trim())} pattern="[a-f0-9]{64}" maxLength={64} required /></label>
      <label>目标运行目录<input aria-label="目标运行目录" value={runDirectory} onChange={event => { setRunDirectory(event.target.value); setReadAuthorized(false); }} required autoComplete="off" /></label>
      {stabilityDirectories.map((value, index) => <label key={index}>稳定性运行目录 {index + 1}<input aria-label={`稳定性运行目录 ${index + 1}`} value={value} onChange={event => { setStability(index, event.target.value); setReadAuthorized(false); }} required autoComplete="off" /></label>)}
      <label>稳定性摘要 JSON<input aria-label="稳定性摘要 JSON" value={summaryPath} onChange={event => setSummaryPath(event.target.value)} required autoComplete="off" /></label>
      <label>稳定性摘要 SHA-256<input aria-label="稳定性摘要 SHA-256" value={summarySha} onChange={event => setSummarySha(event.target.value.trim())} pattern="[a-f0-9]{64}" required /></label>
      <label>来源绑定 JSON<input aria-label="来源绑定 JSON" value={bindingPath} onChange={event => setBindingPath(event.target.value)} required autoComplete="off" /></label>
      <label>来源绑定文件 SHA-256<input aria-label="来源绑定文件 SHA-256" value={bindingFileSha} onChange={event => setBindingFileSha(event.target.value.trim())} pattern="[a-f0-9]{64}" required /></label>
      <label>来源绑定内容 SHA-256<input aria-label="来源绑定内容 SHA-256" value={bindingSha} onChange={event => setBindingSha(event.target.value.trim())} pattern="[a-f0-9]{64}" required /></label>
      <label>来源索引 JSON<input aria-label="来源索引 JSON" value={indexPath} onChange={event => setIndexPath(event.target.value)} required autoComplete="off" /></label>
      <label>来源索引文件 SHA-256<input aria-label="来源索引文件 SHA-256" value={indexFileSha} onChange={event => setIndexFileSha(event.target.value.trim())} pattern="[a-f0-9]{64}" required /></label>
      <label>来源索引内容 SHA-256<input aria-label="来源索引内容 SHA-256" value={indexSha} onChange={event => setIndexSha(event.target.value.trim())} pattern="[a-f0-9]{64}" required /></label>
      <label>Backbone 权重绝对路径<input aria-label="Backbone 权重绝对路径" value={backbonePath} onChange={event => setBackbonePath(event.target.value)} required autoComplete="off" /></label>
      <label>Backbone 权重 SHA-256<input aria-label="Backbone 权重 SHA-256" value={backboneSha} onChange={event => setBackboneSha(event.target.value.trim())} pattern="[a-f0-9]{64}" required /></label>
      <ApprovalFields value={review} onChange={setReview} />
      <Check label="我授权读取上述本地证据文件并逐项核验摘要。" checked={readAuthorized} onChange={setReadAuthorized} />
      <Check label="我仅授权 weights-only 模式校验 pack；不授权任意对象反序列化。" checked={weightsOnly} onChange={setWeightsOnly} />
      <Check label="我已核查 Ultralytics AGPL-3.0 / Enterprise 的适用性；这不是法律结论。" checked={license} onChange={setLicense} />
      <button type="submit" disabled={!ready}>核验并登记 Normality 模型包</button>
    </fieldset></form>;
}

function NormalityAssetForm({ canAct, execute }: { canAct: boolean; execute: Execute }) {
  const [name, setName] = useState(''), [path, setPath] = useState(''), [sha, setSha] = useState(''); const [read, setRead] = useState(false);
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }); const ready = name.trim() && path.trim() && digestValid(sha) && read && approvalReady(review);
  return <form className="vision-models__normality-asset" onSubmit={event => { event.preventDefault(); if (!ready) return;
    void execute('register_inference_asset', key => ({ ...approval(review, key), display_name: name.trim(), image_path: path.trim(), expected_image_sha256: sha,
      operator_attests_read_authorized: read } as RegisterVisionInferenceAssetRequest)).then(ok => { if (ok) { setPath(''); setRead(false); } }); }}>
    <h3>冻结输入图像</h3><p>图像复制到项目级内容寻址存储并绑定摘要；不上传第三方，也不把文件名当标签。</p>
    <fieldset disabled={!canAct}><label>输入图像名称<input aria-label="输入图像名称" value={name} onChange={event => setName(event.target.value)} maxLength={120} required /></label>
      <label>输入图像绝对路径<input aria-label="输入图像绝对路径" value={path} onChange={event => { setPath(event.target.value); setRead(false); }} required autoComplete="off" /></label>
      <label>输入图像 SHA-256<input aria-label="输入图像 SHA-256" value={sha} onChange={event => setSha(event.target.value.trim())} pattern="[a-f0-9]{64}" maxLength={64} required /></label>
      <ApprovalFields value={review} onChange={setReview} /><Check label="我授权读取该本地图像并冻结为当前项目的推理输入；不把目录或文件名解释为真值。" checked={read} onChange={setRead} />
      <button type="submit" disabled={!ready}>冻结为推理输入资产</button></fieldset></form>;
}

function NormalityInferenceForm({ canAct, execute, models, assets, runtimes, ttt }: { canAct: boolean; execute: Execute; models: VisionNormalityModel[]; assets: VisionInferenceAsset[]; runtimes: VisionRuntime[]; ttt?: VisionTttCapabilities }) {
  const [modelId, setModelId] = useState(''), [assetId, setAssetId] = useState(''), [maxSeconds, setMaxSeconds] = useState(120);
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }); const [execution, setExecution] = useState(false), [runtimeTrusted, setRuntimeTrusted] = useState(false);
  const [weightsTrusted, setWeightsTrusted] = useState(false), [weightsOnly, setWeightsOnly] = useState(false);
  const [roles, setRoles] = useState<Record<string, 'adaptation' | 'replay' | 'guard_normal' | 'guard_anomaly' | ''>>({});
  const [tttAuthorized, setTttAuthorized] = useState(false), [replayNormal, setReplayNormal] = useState(false), [guardReviewed, setGuardReviewed] = useState(false);
  const [budget, setBudget] = useState<VisionTttBudget>({ steps: 2, learning_rate: .001, max_seconds: 30, seed: 0 });
  const model = models.find(item => item.model_id === modelId), asset = assets.find(item => item.asset_id === assetId);
  const runtime = runtimes.find(item => item.runtime_id === model?.sandbox_runtime_id); const runtimeReady = runtime?.probe.status === 'ready' && runtime.probe.import_status === 'PASSED' && runtime.runtime_sha256 === model?.sandbox_runtime_sha256;
  useEffect(() => { setExecution(false); setRuntimeTrusted(false); setWeightsTrusted(false); setWeightsOnly(false); setTttAuthorized(false); setReplayNormal(false); setGuardReviewed(false); }, [modelId, assetId, model?.receipt_sha256, asset?.receipt_sha256, roles, budget, maxSeconds, ttt?.receipt_sha256, assets]);
  const refs = (role: string) => assets.filter(row => row.asset_id !== assetId && roles[row.asset_id] === role).map(row => ({ asset_id: row.asset_id, expected_asset_receipt_sha256: row.receipt_sha256, expected_image_sha256: row.image_sha256 }));
  const adaptation = refs('adaptation'), replay = refs('replay'), guard = [...refs('guard_normal').map(row => ({ ...row, reference_label: 'normal' })), ...refs('guard_anomaly').map(row => ({ ...row, reference_label: 'anomaly' }))];
  const hashes = [asset?.image_sha256, ...[...adaptation, ...replay, ...guard].map(row => row.expected_image_sha256)];
  const tttReady = !ttt || (tttAuthorized && replayNormal && guardReviewed && adaptation.length <= 7 && replay.length >= 1 && replay.length <= 8 && guard.length >= 2 && guard.length <= 16
    && guard.some(row => row.reference_label === 'normal') && guard.some(row => row.reference_label === 'anomaly') && new Set(hashes).size === hashes.length
    && Number.isInteger(budget.steps) && budget.steps >= 1 && budget.steps <= 8 && budget.learning_rate >= .00001 && budget.learning_rate <= .01 && Number.isInteger(budget.max_seconds)
    && budget.max_seconds >= 5 && budget.max_seconds <= 120 && budget.max_seconds <= maxSeconds && Number.isInteger(budget.seed) && budget.seed >= 0 && budget.seed <= 2147483647);
  const ready = Boolean(model && asset && runtimeReady && maxSeconds >= 5 && maxSeconds <= 300 && execution && runtimeTrusted && weightsTrusted && weightsOnly && approvalReady(review) && tttReady);
  return <form className={ttt ? 'vision-models__normality-ttt' : 'vision-models__normality-inference'} onSubmit={event => { event.preventDefault(); if (!model || !asset || !ready) return;
    void execute(`${ttt ? 'run_normality_ttt' : 'run_normality_inference'}:${model.model_id}`, key => ({ ...approval(review, key), expected_model_receipt_sha256: model.receipt_sha256,
      expected_model_pack_sha256: model.model_pack_sha256, expected_backbone_weights_sha256: model.backbone_weights_sha256, expected_source_binding_sha256: model.source_binding_sha256,
      expected_source_index_sha256: model.source_index_sha256, expected_runtime_sha256: model.sandbox_runtime_sha256!, asset_id: asset.asset_id,
      expected_asset_receipt_sha256: asset.receipt_sha256, expected_image_sha256: asset.image_sha256, max_seconds: maxSeconds, operator_attests_execution_authorized: execution,
      operator_attests_trusted_runtime: runtimeTrusted, operator_attests_trusted_weights: weightsTrusted, operator_attests_weights_only_load_authorized: weightsOnly,
      ...(ttt ? { expected_ttt_implementation_sha256: ttt.implementation_sha256, adaptation_assets: adaptation, replay_assets: replay, guard_assets: guard, budget,
        operator_attests_ttt_authorized: tttAuthorized, operator_attests_replay_normal: replayNormal, operator_attests_guard_labels_reviewed: guardReviewed } : {}) } as RunNormalityInferenceRequest)).then(ok => { if (ok) { setExecution(false); setRuntimeTrusted(false); setWeightsTrusted(false); setWeightsOnly(false); setTttAuthorized(false); setReplayNormal(false); setGuardReviewed(false); } }); }}>
    <h3>{ttt ? '单次 TTT 输入、预算与授权' : '3 · 执行一次本地沙箱推理'}</h3><p>只有 `APPROVE_SANDBOX` 的 pack 和 `PASSED` 的绑定运行环境可选。输出永远保持 `NOT_ISSUED`，必须由人继续复核。</p>
    <fieldset disabled={!canAct}><label>Normality 模型包<select aria-label="Normality 模型包" value={modelId} onChange={event => setModelId(event.target.value)} required><option value="">选择已批准模型包</option>{models.map(item => <option key={item.model_id} value={item.model_id}>{item.display_name} · {item.status}</option>)}</select></label>
      <label>冻结输入资产<select aria-label="冻结输入资产" value={assetId} onChange={event => setAssetId(event.target.value)} required><option value="">选择已冻结图像</option>{assets.map(item => <option key={item.asset_id} value={item.asset_id}>{item.display_name} · {item.image_width}×{item.image_height}</option>)}</select></label>
      <label>最长执行秒数<input aria-label="最长执行秒数" type="number" min={5} max={300} value={maxSeconds} onChange={event => setMaxSeconds(event.target.valueAsNumber)} /></label>
      {ttt && <><Sha label="TTT 实现 SHA-256" value={ttt.implementation_sha256} /><p>query 自动参与 adaptation；replay 必须是正常旧参考；guard 必须由人复核且包含正常与异常，三个集合按图像 SHA 隔离。guard 只检查，不参与梯度更新。</p>
        {assets.filter(row => row.asset_id !== assetId).map(row => <label key={row.asset_id}>{row.display_name}<select aria-label={`TTT 用途 ${row.asset_id}`} value={roles[row.asset_id] ?? ''} onChange={event => setRoles(current => ({ ...current, [row.asset_id]: event.target.value as typeof roles[string] }))}><option value="">不参与</option><option value="adaptation">额外适应图（不使用标签）</option><option value="replay">正常 replay（人工确认）</option><option value="guard_normal">独立 guard · 正常（人工标签）</option><option value="guard_anomaly">独立 guard · 异常（人工标签）</option></select></label>)}
        <div className="vision-models__budget">{([{ key: 'steps', label: 'TTT 步数', min: 1, max: 8, step: 1 }, { key: 'learning_rate', label: 'TTT 学习率', min: .00001, max: .01, step: .00001 }, { key: 'max_seconds', label: 'TTT 最长秒数', min: 5, max: 120, step: 1 }, { key: 'seed', label: 'TTT Seed', min: 0, max: 2147483647, step: 1 }] as const).map(field => <label key={field.key}>{field.label}<input aria-label={field.label} type="number" min={field.min} max={field.max} step={field.step} value={budget[field.key]} onChange={event => setBudget(current => ({ ...current, [field.key]: event.target.valueAsNumber }))} /></label>)}</div></>}
      {model && <><Sha label="模型包 SHA-256" value={model.model_pack_sha256} /><Sha label="绑定运行环境 SHA-256" value={model.sandbox_runtime_sha256!} />{!runtimeReady && <p className="vision-models__inline-hold">HOLD：批准时绑定的运行环境不在当前项目，或实际库导入不是 PASSED。</p>}</>}
      {asset && <Sha label="输入图像 SHA-256" value={asset.image_sha256} />}<ApprovalFields value={review} onChange={setReview} />
      <Check label="我授权本次本地 CPU 推理；结果只作为模型信号。" checked={execution} onChange={setExecution} />
      <Check label="我信任沙箱运行环境，并确认绑定 SHA 未变。" checked={runtimeTrusted} onChange={setRuntimeTrusted} />
      <Check label="我信任绑定的权重与证据来源。" checked={weightsTrusted} onChange={setWeightsTrusted} />
      <Check label="我仅授权 weights-only 加载模型包。" checked={weightsOnly} onChange={setWeightsOnly} />
      {ttt && <><Check label="我单独授权本次有界 TTT，仅改变本次学生副本；结束即重置，不持久训练原模型。" checked={tttAuthorized} onChange={setTttAuthorized} /><Check label="我确认 replay 图像是经人工核查的正常旧参考，不由文件名或模型预测推定。" checked={replayNormal} onChange={setReplayNormal} /><Check label="我已具名复核 guard 的正常与异常标签，授权它们仅用于独立遗忘与回滚检查。" checked={guardReviewed} onChange={setGuardReviewed} /></>}
      <button type="submit" disabled={!ready}>{ttt ? '按独立授权执行一次 TTT' : '执行一次本地沙箱推理'}</button>
    </fieldset></form>;
}

function DatasetForm({ canAct, execute }: { canAct: boolean; execute: Execute }) {
  const [path, setPath] = useState(''); const [loaded, setLoaded] = useState<{ manifest: DetectionManifest; sha256: string }>();
  const [parsing, setParsing] = useState(false), [error, setError] = useState(''), [authorized, setAuthorized] = useState(false);
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }); const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  const readFile = async (file?: File) => {
    const epoch = ++generation.current; setLoaded(undefined); setAuthorized(false); setError('');
    if (!file) return; if (file.size > 2 * 1024 * 1024) { setError('清单超过 2 MiB，未读取。'); return; }
    setParsing(true);
    try { const result = await parseDetectionManifest(await file.text()); if (generation.current === epoch) setLoaded(result); }
    catch { if (generation.current === epoch) setError('清单不符合明确检测框、具名复核或 train/val/test 隔离合同；没有从类别备注或 mask 猜测真值。'); }
    finally { if (generation.current === epoch) setParsing(false); }
  };
  return <form onSubmit={event => { event.preventDefault(); if (!loaded) return; void execute('register_dataset', key => ({ ...approval(review, key), source_root: path.trim(), manifest: loaded.manifest, expected_manifest_sha256: loaded.sha256, operator_attests_data_authorized: authorized })).then(ok => { if (ok) { setPath(''); setAuthorized(false); } }); }}>
    <h3>冻结已复核的检测数据</h3><p>读取本地 JSON 清单，在浏览器计算原始对象的 JCS SHA；图像仅由本机后端按授权目录读取。清单不保存到浏览器存储。</p>
    {error && <div role="alert" className="vision-models__inline-hold">{error}</div>}
    <fieldset disabled={!canAct || parsing}><label>检测清单 JSON<input type="file" accept="application/json,.json" onChange={e => void readFile(e.target.files?.[0])} /></label>
      {parsing && <p role="status">正在校验清单并计算摘要…</p>}
      {loaded && <div className="vision-models__manifest"><strong>结构检查通过 · 尚未冻结</strong><span>{loaded.manifest.samples.length} 个样本 · {loaded.manifest.class_names.length} 类</span>
        <div className="vision-models__splits">{(['train', 'val', 'test'] as const).map(split => <span key={split}>{split}<b>{loaded.manifest.samples.filter(s => s.split === split).length}</b></span>)}</div><Sha label="原始 manifest JCS SHA-256" value={loaded.sha256} /></div>}
      <label>图像源目录绝对路径<input value={path} onChange={e => { setPath(e.target.value); setAuthorized(false); }} maxLength={2048} autoComplete="off" spellCheck={false} required /></label>
      <p className="vision-models__inline-hold">至少各有一个 train / val / test；采集组、图像与像素不能跨集合。验证 / 测试数据不会回灌训练。空框必须有明确正常样本声明。</p>
      <ApprovalFields value={review} onChange={setReview} />
      <Check label="我确认清单中的检测框已经具名复核，并授权读取源目录与冻结训练数据副本。" checked={authorized} onChange={setAuthorized} />
      <button type="submit" disabled={!loaded || !path.trim() || !authorized || !approvalReady(review)}>核验源文件并登记数据集</button>
    </fieldset></form>;
}

function PoolDatasetForm({ scope, poolId, expectedVersionId, canAct, execute }: { scope: VisionScope; poolId: string; expectedVersionId: string | null; canAct: boolean; execute: Execute }) {
  const [projection, setProjection] = useState<DataPoolProjection>(); const [loading, setLoading] = useState(false), [error, setError] = useState('');
  const [classes, setClasses] = useState(''), [groups, setGroups] = useState<Record<string, string>>({}), [normalIds, setNormalIds] = useState<string[]>([]);
  const [authorized, setAuthorized] = useState(false); const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' });
  const mounted = useRef(true); useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const load = async () => {
    if (loading || getIdentityActorId() !== scope.actorId) return;
    setLoading(true); setProjection(undefined); setError(''); setGroups({}); setNormalIds([]); setAuthorized(false);
    try { const result = await getVisionPool(scope, poolId, expectedVersionId); if (mounted.current && getIdentityActorId() === scope.actorId) setProjection(result); }
    catch { if (mounted.current) setError('HOLD：数据池回执、项目或指定版本未匹配。旧版本链接不会自动切换到新版本；请回数据池重新复核后进入。'); }
    finally { if (mounted.current) setLoading(false); }
  };
  const version = projection?.current_version; const members = version?.members ?? [];
  const classNames = classes.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  const eligible = projection?.read_status === 'CURRENT' && version?.status === 'REVIEWED_ALL_QUALIFIED_REFERENCE' && version.preflight_receipt_sha256 !== null
    && version.readiness_blockers.length === 0 && version.global_finding_refs.length === 0 && version.unmapped_finding_refs.length === 0 && members.length >= 3 && members.length <= 64
    && version.qualified_count === members.length && new Set(members.map(member => member.split)).size === 3
    && members.every(member => member.disposition === 'QUALIFIED_CANDIDATE' && member.repair_action === 'NONE' && member.repair_result === 'NOT_APPLICABLE' && member.finding_refs.length === 0);
  const groupsComplete = members.length > 0 && Object.keys(groups).length === members.length && members.every(member => groups[member.sample_id]?.trim());
  const validClasses = classNames.length >= 1 && classNames.length <= 64 && new Set(classNames).size === classNames.length;
  return <form className="vision-models__pool-form" onSubmit={event => {
    event.preventDefault(); if (!projection || !version || !eligible || !groupsComplete || !validClasses || !authorized) return;
    void execute('register_pool_dataset', key => ({ ...approval(review, key), pool_id: projection.pool.pool_id, version_id: version.version_id,
      expected_pool_receipt_sha256: projection.pool.receipt_sha256, expected_version_receipt_sha256: version.receipt_sha256,
      class_names: classNames, groups: Object.fromEntries(members.map(member => [member.sample_id, groups[member.sample_id]!.trim()])),
      normal_sample_ids: normalIds, operator_attests_data_authorized: authorized })).then(() => setAuthorized(false));
  }}>
    <h3>从当前数据池登记检测数据</h3><p>后端读取已冻结、具名复核的原始检测框，并核对图像、标注和版本。这里不提交服务器路径，不从 mask 或类别备注猜测标签。</p>
    <button type="button" disabled={loading} onClick={() => void load()}>{loading ? '读取并核验中…' : '读取指定数据池版本（仅 GET）'}</button>
    {error && <p role="alert" className="vision-models__inline-hold">{error}</p>}
    {projection && version && <><Sha label="数据池回执 SHA-256" value={projection.pool.receipt_sha256} /><Sha label="指定版本回执 SHA-256" value={version.receipt_sha256} />
      <code>{version.version_id}</code>
      {!eligible && <p className="vision-models__inline-hold">HOLD：需当前全员 qualified、完整 Gate PASS、无未处置项，并且 train / val / test 均存在。请回数据池修复并完成新快照 / Gate，不在本页跳过。</p>}
      <fieldset disabled={!canAct || !eligible || loading}>
        <label>冻结类别词表（每行一类）<textarea value={classes} onChange={e => { setClasses(e.target.value); setAuthorized(false); }} rows={3} required /></label>
        <small>必须与快照验收词表完全一致；排列顺序固定 class_id。来源中的 category 备注不是检测框真值。</small>
        <div className="vision-models__pool-members">{members.map(member => <div className="vision-models__pool-member" key={member.sample_id}>
          <strong>{member.sample_id}<span>{member.split}</span></strong><small>标注 revision {member.annotation_revision} · {member.annotation_sha256.slice(0, 12)}…</small>
          <label>采集组 · {member.sample_id}<input value={groups[member.sample_id] ?? ''} maxLength={160} required autoComplete="off" onChange={e => { setGroups({ ...groups, [member.sample_id]: e.target.value }); setAuthorized(false); }} /></label>
          {['OPTIONAL', 'NOT_APPLICABLE'].includes(member.annotation_requirement) ? <Check label={`已核实 ${member.sample_id} 为无前景空框样本`} checked={normalIds.includes(member.sample_id)} onChange={checked => { setNormalIds(current => checked ? [...current, member.sample_id] : current.filter(id => id !== member.sample_id)); setAuthorized(false); }} /> : <small>该样本要求明确标注，不能用空框正常声明替代。</small>}
        </div>)}</div>
        <p className="vision-models__inline-hold">相同采集组不能跨 split；验证 / 测试成员保持原集合。空框声明必须精确匹配后端观察，不勾选即不授权补零。全部成员都要纳入，不能在此偷偷筛子集。</p>
        <ApprovalFields value={review} onChange={setReview} />
        <Check label="我已复核固定词表、全部成员采集组和每个空框声明，并明确授权从这个池版本读取原始检测框、冻结数据副本。" checked={authorized} onChange={setAuthorized} />
        <button type="submit" disabled={!groupsComplete || !validClasses || !authorized || !approvalReady(review)}>从已复核池版本登记检测数据集</button>
      </fieldset></>}
  </form>;
}

function TrainingForm({ canAct, execute, runtimes, datasets, models, feedback, activeRun }: { canAct: boolean; execute: Execute; runtimes: VisionRuntime[]; datasets: VisionDataset[]; models: VisionModel[]; feedback: VisionFeedback[]; activeRun: boolean }) {
  const [runtimeId, setRuntimeId] = useState(''), [datasetId, setDatasetId] = useState(''), [modelId, setModelId] = useState('');
  const [initialization, setInitialization] = useState<'ARCHITECTURE_RANDOM' | 'REGISTERED_WEIGHTS'>('ARCHITECTURE_RANDOM');
  const [budget, setBudget] = useState<VisionBudget>({ epochs: 1, imgsz: 64, batch: 2, seed: 0, max_seconds: 120, threads: 2 });
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' });
  const [trainingAuthorized, setTrainingAuthorized] = useState(false), [runtimeTrusted, setRuntimeTrusted] = useState(false);
  const [weightsTrusted, setWeightsTrusted] = useState(false), [pickleAuthorized, setPickleAuthorized] = useState(false), [license, setLicense] = useState(false);
  const [feedbackIds, setFeedbackIds] = useState<string[]>([]);
  const runtime = runtimes.find(item => item.runtime_id === runtimeId), dataset = datasets.find(item => item.dataset_id === datasetId), model = models.find(item => item.model_id === modelId);
  useEffect(() => { setTrainingAuthorized(false); setRuntimeTrusted(false); setWeightsTrusted(false); setPickleAuthorized(false); }, [runtimeId, datasetId, modelId, initialization, runtime?.receipt_sha256, dataset?.receipt_sha256, model?.receipt_sha256]);
  const suitableModel = model?.task_type === 'detect' && model.format === 'pt';
  const runtimeReady = runtime?.probe.status === 'ready' && runtime.probe.import_status !== 'FAILED';
  const eligible = Boolean(runtimeReady && dataset && (initialization === 'ARCHITECTURE_RANDOM' || suitableModel && weightsTrusted && pickleAuthorized));
  const chosenFeedback = feedback.filter(item => feedbackIds.includes(item.feedback_id));
  const feedbackReady = chosenFeedback.length === feedbackIds.length && chosenFeedback.every(item => {
    const previous = datasets.find(row => row.dataset_id === item.dataset_id);
    return item.status === 'TRIAGED_FOR_REVIEW' && item.classification !== 'UNKNOWN' && previous && dataset && dataset.dataset_receipt_sha256 !== item.dataset_receipt_sha256
      && (!previous.pool_binding || dataset.pool_binding && dataset.pool_binding.version_id !== previous.pool_binding.version_id && dataset.pool_binding.task_id !== previous.pool_binding.task_id);
  });
  const formReady = eligible && feedbackReady && !activeRun && trainingAuthorized && runtimeTrusted && license && approvalReady(review);
  return <form onSubmit={event => { event.preventDefault(); if (!runtime || !dataset || !formReady) return;
    void execute('create_training_run', key => ({ ...approval(review, key), runtime_id: runtime.runtime_id, expected_runtime_sha256: runtime.runtime_sha256, dataset_id: dataset.dataset_id,
      expected_dataset_receipt_sha256: dataset.dataset_receipt_sha256, initialization, initial_model_id: initialization === 'REGISTERED_WEIGHTS' ? model!.model_id : null,
      expected_weights_sha256: initialization === 'REGISTERED_WEIGHTS' ? model!.weights_sha256 : null, architecture: 'yolo26n', training: budget, adaptation: 'OFF',
      operator_attests_training_authorized: trainingAuthorized, operator_attests_trusted_runtime: runtimeTrusted,
      operator_attests_trusted_weights: initialization === 'REGISTERED_WEIGHTS' && weightsTrusted, operator_attests_pickle_load_risk: initialization === 'REGISTERED_WEIGHTS' && pickleAuthorized,
      ultralytics_license_acknowledged: license, responds_to_feedback_ids: feedbackIds, expected_feedback_receipts: Object.fromEntries(chosenFeedback.map(item => [item.feedback_id, item.receipt_sha256])) } as CreateVisionRunRequest)).then(() => { setTrainingAuthorized(false); setRuntimeTrusted(false); setWeightsTrusted(false); setPickleAuthorized(false); setLicense(false); }); }}>
    <h3>发起一次有界 CPU 训练</h3><p>仅训练 train；val 用于基线 / 候选对比，test 保留且不执行评测。关闭页面不会自动发起第二次训练。</p>
    {activeRun && <div className="vision-models__inline-hold">HOLD：当前项目有 QUEUED / RUNNING 任务。请在右侧刷新或申请取消，不并行重复启动。</div>}
    <fieldset disabled={!canAct || activeRun}><label>运行环境<select aria-label="运行环境" value={runtimeId} onChange={e => setRuntimeId(e.target.value)} required><option value="">请选择已登记环境</option>{runtimes.map(item => <option key={item.runtime_id} value={item.runtime_id}>{item.display_name} · {item.probe.status} / {item.probe.import_status}</option>)}</select></label>
      {runtime && <><Sha label="运行环境指纹（不是 exe SHA）" value={runtime.runtime_sha256} />{!runtimeReady && <p className="vision-models__inline-hold">HOLD：所选环境缺少当前后端能力；未安装或切换环境。</p>}</>}
      <label>冻结数据集<select aria-label="冻结数据集" value={datasetId} onChange={e => setDatasetId(e.target.value)} required><option value="">请选择已登记检测数据集</option>{datasets.map(item => <option key={item.dataset_id} value={item.dataset_id}>{item.dataset_receipt.source_version} · {item.dataset_receipt.samples.length} 样本</option>)}</select></label>
      {dataset && <Sha label="冻结数据集 SHA-256" value={dataset.dataset_receipt_sha256} />}
      <div className="vision-models__feedback-link"><h4>回应已复核反馈（可选）</h4><p>先在右侧读取并人工分类上一轮反馈。选中的反馈只建立证据关联，不自动关闭问题，也不允许 val / test 回灌训练。</p>
        {!feedback.length && <small>尚未读取反馈，不代表没有问题。本轮可以作为无反馈关联的独立训练。</small>}
        {feedback.map(item => item.status === 'TRIAGED_FOR_REVIEW' && item.classification !== 'UNKNOWN'
          ? <Check key={item.feedback_id} label={`${item.sample_id} · ${item.classification} · ${item.feedback_id}`} checked={feedbackIds.includes(item.feedback_id)} onChange={checked => { setFeedbackIds(current => checked ? [...current, item.feedback_id] : current.filter(id => id !== item.feedback_id)); setTrainingAuthorized(false); }} />
          : <small key={item.feedback_id}>{item.sample_id}：尚未分类或分类为 UNKNOWN，不能作为新轮次回应。</small>)}
        {!feedbackReady && <p className="vision-models__inline-hold">HOLD：回应反馈必须选择不同 SHA 的新数据集；旧数据来自数据池时，还必须是新的池版本和新的 Task / Gate。请先完成新数据复核，不自动搬移验证样本。</p>}
      </div>
      <label>初始化方式<select value={initialization} onChange={e => setInitialization(e.target.value as typeof initialization)}><option value="ARCHITECTURE_RANDOM">YOLO26n 架构随机初始化（非预训练）</option><option value="REGISTERED_WEIGHTS">加载已登记的本地 .pt 权重</option></select></label>
      {initialization === 'ARCHITECTURE_RANDOM' ? <p>从已安装架构配置建立新模型，不会下载预训练权重。少量轮次只适合验证工程链路。</p> : <><label>本地初始权重<select value={modelId} onChange={e => setModelId(e.target.value)} required><option value="">选择 detect / .pt 权重</option>{models.map(item => <option key={item.model_id} value={item.model_id}>{item.display_name} · {item.task_type} / {item.format}</option>)}</select></label>
        {model && <Sha label="初始权重 SHA-256" value={model.weights_sha256} />}{model && !suitableModel && <p className="vision-models__inline-hold">HOLD：该登记任务或格式不支持当前训练；不会隐式转换。</p>}
        <Check label="我确认所选权重来自可信来源，并授权加载此 SHA 对应的权重。" checked={weightsTrusted} onChange={setWeightsTrusted} />
        <Check label="我单独确认 .pt 可能包含可执行 pickle 的风险，并授权本次反序列化。登记本身不代表此授权。" checked={pickleAuthorized} onChange={setPickleAuthorized} /></>}
      <div className="vision-models__budget">{([{ key: 'epochs', label: '轮次', min: 1, max: 5 }, { key: 'imgsz', label: '图像尺寸', min: 64, max: 320, step: 32 }, { key: 'batch', label: 'Batch', min: 2, max: 8 }, { key: 'max_seconds', label: '最长秒数', min: 10, max: 600 }, { key: 'threads', label: 'CPU 线程', min: 1, max: 4 }, { key: 'seed', label: 'Seed', min: 0, max: 2147483647 }] as const).map(field => <label key={field.key}>{field.label}<input type="number" value={budget[field.key]} min={field.min} max={field.max} step={'step' in field ? field.step : 1} required onChange={e => { setBudget({ ...budget, [field.key]: e.target.valueAsNumber }); setTrainingAuthorized(false); }} /></label>)}</div>
      <ApprovalFields value={review} onChange={setReview} />
      <Check label="我已核查 Ultralytics AGPL-3.0 / Enterprise 许可适用性；本操作不是法律合规确认。" checked={license} onChange={setLicense} />
      <Check label="我信任所选 Python 运行环境，并授权执行已安装的模型库。" checked={runtimeTrusted} onChange={setRuntimeTrusted} />
      <Check label="我授权按上述数据集、初始模型与预算执行一次 CPU 监督训练；候选完成不等于精度 PASS，也不接生产。" checked={trainingAuthorized} onChange={setTrainingAuthorized} />
      <button type="submit" disabled={!formReady}>按本次授权启动 CPU 训练</button>
    </fieldset></form>;
}

function NormalityRecordDetails({ record, scope, canAct, execute, runtimes }: { record: VisionNormalityModel | VisionInferenceAsset | VisionInference; scope: VisionScope; canAct: boolean; execute: Execute; runtimes: VisionRuntime[] }) {
  if ('inference_id' in record) return <NormalityInferenceDetails inference={record} scope={scope} canAct={canAct} execute={execute} />;
  if ('asset_id' in record) return <article className="vision-models__details"><h4>冻结推理输入资产</h4><code>{record.asset_id}</code><Sha label="资产回执 SHA-256" value={record.receipt_sha256} />
    <Sha label="图像 SHA-256" value={record.image_sha256} /><dl><dt>尺寸</dt><dd>{record.image_width} × {record.image_height}</dd><dt>格式 / 字节</dt><dd>{record.format} · {record.image_bytes.toLocaleString()}</dd>
      <dt>存储</dt><dd>{record.storage_scope}</dd><dt>标签真值</dt><dd>未声明；文件名和目录不作为真值</dd><dt>生产放行</dt><dd>禁止 · false</dd></dl></article>;
  return <article className="vision-models__details"><h4>Normality 模型包</h4><code>{record.model_id}</code><Sha label="模型回执 SHA-256" value={record.receipt_sha256} />
    <Sha label="模型包 SHA-256" value={record.model_pack_sha256} /><Sha label="Backbone SHA-256" value={record.backbone_weights_sha256} />
    <dl><dt>状态</dt><dd>{record.status}</dd><dt>使用范围</dt><dd>{record.usage_scope}</dd><dt>稳定性证据</dt><dd>{record.stability_status} · 3 个绑定运行</dd>
      <dt>执行设备</dt><dd>尚未加载；批准后仅绑定本地 CPU 运行环境</dd><dt>生产放行</dt><dd>禁止 · false</dd></dl>
    {['MODEL_PACK_EVIDENCE_VERIFIED', 'APPROVE_SANDBOX'].includes(record.status) && <NormalityApprovalForm model={record} runtimes={runtimes} canAct={canAct} execute={execute} />}
    {record.status === 'APPROVE_SANDBOX' && <><Sha label="沙箱运行环境 SHA-256" value={record.sandbox_runtime_sha256!} /><p>已批准为本地沙箱模型；这不是工业精度、标签真值或生产发布批准。</p></>}
    {record.status === 'REJECT' && <p className="vision-models__inline-hold">该模型包已被具名人员拒绝，不可执行推理。</p>}
  </article>;
}

function NormalityApprovalForm({ model, runtimes, canAct, execute }: { model: VisionNormalityModel; runtimes: VisionRuntime[]; canAct: boolean; execute: Execute }) {
  const [runtimeId, setRuntimeId] = useState(''), [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' });
  const [reviewed, setReviewed] = useState(false), [trustedRuntime, setTrustedRuntime] = useState(false), [execution, setExecution] = useState(false);
  const [trustedWeights, setTrustedWeights] = useState(false), [weightsOnly, setWeightsOnly] = useState(false), [license, setLicense] = useState(false);
  const runtime = runtimes.find(item => item.runtime_id === runtimeId); const readyRuntime = runtime?.probe.status === 'ready' && runtime.probe.import_status === 'PASSED';
  const submit = (action: 'APPROVE_SANDBOX' | 'REJECT') => { if (!runtime) return; void execute(`approve_normality_model_pack:${model.model_id}`, key => ({ ...approval(review, key), action,
    expected_model_receipt_sha256: model.receipt_sha256, expected_model_pack_sha256: model.model_pack_sha256, expected_backbone_weights_sha256: model.backbone_weights_sha256,
    expected_source_binding_sha256: model.source_binding_sha256, expected_source_index_sha256: model.source_index_sha256, runtime_id: runtime.runtime_id,
    expected_runtime_sha256: runtime.runtime_sha256, operator_attests_reviewed: reviewed, operator_attests_trusted_runtime: trustedRuntime,
    operator_attests_execution_authorized: execution, operator_attests_trusted_weights: trustedWeights, operator_attests_weights_only_load_authorized: weightsOnly,
    ultralytics_license_acknowledged: license } as ApproveNormalityModelPackRequest)); };
  const ready = Boolean(readyRuntime && reviewed && trustedRuntime && execution && trustedWeights && weightsOnly && license && approvalReady(review));
  return <form className="vision-models__normality-approval" onSubmit={event => event.preventDefault()}><h4>具名沙箱批准</h4><p>批准会在所选解释器中执行真实 pack 校验；登记本身不能继承执行授权。</p><fieldset disabled={!canAct}>
    <label>沙箱运行环境<select aria-label="沙箱运行环境" value={runtimeId} onChange={event => { setRuntimeId(event.target.value); setReviewed(false); }} required><option value="">选择已完成真实库导入的环境</option>{runtimes.map(item => <option key={item.runtime_id} value={item.runtime_id}>{item.display_name} · {item.probe.import_status}</option>)}</select></label>
    {runtime && !readyRuntime && <p className="vision-models__inline-hold">HOLD：该环境的实际库导入不是 PASSED，不能批准模型包。</p>}<ApprovalFields value={review} onChange={setReview} />
    <Check label="我已复核模型包证据和当前回执 SHA。" checked={reviewed} onChange={setReviewed} /><Check label="我信任所选运行环境。" checked={trustedRuntime} onChange={setTrustedRuntime} />
    <Check label="我授权执行模型包验证。" checked={execution} onChange={setExecution} /><Check label="我信任绑定的权重。" checked={trustedWeights} onChange={setTrustedWeights} />
    <Check label="我仅授权 weights-only 加载。" checked={weightsOnly} onChange={setWeightsOnly} /><Check label="我已核查 Ultralytics 许可适用性。" checked={license} onChange={setLicense} />
    <div className="vision-models__actions"><button type="button" disabled={!ready} onClick={() => submit('APPROVE_SANDBOX')}>{model.status === 'APPROVE_SANDBOX' ? '重新核验沙箱批准' : '批准为本地沙箱模型'}</button><button type="button" disabled={!ready} onClick={() => submit('REJECT')}>拒绝模型包</button></div>
  </fieldset></form>;
}

function NormalityInferenceDetails({ inference, scope, canAct, execute }: { inference: VisionInference; scope: VisionScope; canAct: boolean; execute: Execute }) {
  const [classification, setClassification] = useState<NormalityFeedbackClassification>('INSUFFICIENT_EVIDENCE');
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }), [attested, setAttested] = useState(false);
  const [preview, setPreview] = useState(''), [previewBusy, setPreviewBusy] = useState(false), [previewError, setPreviewError] = useState('');
  const [items, setItems] = useState<NormalityFeedback[]>([]), [feedbackError, setFeedbackError] = useState(''), [feedbackBusy, setFeedbackBusy] = useState(false);
  const alive = useRef(false), url = useRef(''), request = useRef<AbortController | null>(null), readingFeedback = useRef(false);
  const valid = () => alive.current && getIdentityActorId() === scope.actorId;
  const readFeedback = async () => {
    if (!valid() || readingFeedback.current) return; readingFeedback.current = true; setFeedbackBusy(true); setFeedbackError('');
    try { const rows = await getNormalityFeedback(scope, inference); if (valid()) setItems(rows); }
    catch (failure) { if (valid()) { setItems([]); setFeedbackError(visionErrorMessage(failure)); } }
    finally { readingFeedback.current = false; if (valid()) setFeedbackBusy(false); }
  };
  useEffect(() => {
    alive.current = true; void readFeedback();
    return () => { alive.current = false; request.current?.abort(); if (url.current) { URL.revokeObjectURL(url.current); url.current = ''; } };
  }, [scope.actorId, scope.workspaceId, scope.projectId, inference.inference_id, inference.receipt_sha256]);
  const loadPreview = async () => {
    if (!valid() || previewBusy) return; request.current?.abort(); const controller = new AbortController(); request.current = controller;
    if (url.current) { URL.revokeObjectURL(url.current); url.current = ''; } setPreview(''); setPreviewBusy(true); setPreviewError('');
    try {
      const blob = await getVisionHeatmap(scope, inference, controller.signal);
      if (!valid() || controller.signal.aborted || request.current !== controller) return;
      url.current = URL.createObjectURL(blob); setPreview(url.current);
    } catch (failure) { if (valid() && !controller.signal.aborted) setPreviewError(visionErrorMessage(failure)); }
    finally { if (valid() && request.current === controller) setPreviewBusy(false); }
  };
  return <article className="vision-models__details"><h4>Normality 推理回执</h4><code>{inference.inference_id}</code><Sha label="推理回执 SHA-256" value={inference.receipt_sha256} />
    <div className="vision-models__splits"><span>图像分数<b>{inference.image_score.toFixed(6)}</b></span><span>图像阈值<b>{inference.image_threshold.toFixed(6)}</b></span><span>异常信号<b>{inference.predicted_anomaly ? '是' : '否'}</b></span><span>阳性像素占比<b>{inference.positive_pixel_fraction.toFixed(6)}</b></span></div>
    <Sha label="输入图像 SHA-256" value={inference.image_sha256} /><Sha label="模型包 SHA-256" value={inference.model_pack_sha256} /><Sha label="运行环境 SHA-256" value={inference.runtime_sha256} />
    <dl><dt>状态</dt><dd>{inference.status}</dd><dt>决策范围</dt><dd>{inference.decision_scope}</dd><dt>Gate 决策</dt><dd>{inference.gate_decision}</dd><dt>生产放行</dt><dd>禁止 · false</dd></dl>
    {inference.ttt && <TttReportDetails report={inference.ttt} />}
    <section className="vision-models__heatmap-evidence"><h4>Heatmap 工件证据</h4><Sha label="Heatmap SHA-256" value={inference.heatmap.sha256} /><p>{inference.heatmap.width} × {inference.heatmap.height} · {inference.heatmap.format} · {inference.heatmap.bytes.toLocaleString()} bytes</p>
      <p>仅从当前项目读取 PNG，核对实际字节、尺寸、SHA-256 与强 ETag 后显示；切换记录或账号会撤销预览。</p>
      <button type="button" disabled={previewBusy} onClick={() => void loadPreview()}>读取并校验热图（仅 GET）</button>
      {previewError && <p className="vision-models__inline-hold" role="alert">{previewError}</p>}
      {preview && <figure><img src={preview} alt="已校验的 Normality 热图" style={{ maxWidth: '100%', maxHeight: 480, objectFit: 'contain' }} onError={() => { if (url.current) URL.revokeObjectURL(url.current); url.current = ''; setPreview(''); setPreviewError('HOLD：PNG 无法解码；没有接受预览。'); }} /><figcaption>真实工件 · SHA-256 已核验；颜色是模型信号，不是缺陷真值。</figcaption></figure>}</section>
    <form className="vision-models__normality-review" onSubmit={event => { event.preventDefault(); if (!canAct || !attested || !approvalReady(review)) return;
      void execute(`review_normality_inference:${inference.inference_id}`, key => ({ ...approval(review, key), expected_inference_sha256: inference.receipt_sha256, operator_attests_reviewed: attested, classification })); }}>
      <h4>具名人工信号复核</h4><p>明确提交到服务端并 GET 回读，绑定当前推理摘要。已保存反馈不等于标签真值，也不表示已进入训练或创建工单；问题保持开放。</p><fieldset disabled={!canAct}>
      <label>人工信号分类<select aria-label="人工信号分类" value={classification} onChange={event => { setClassification(event.target.value as typeof classification); setAttested(false); }}><option value="INSUFFICIENT_EVIDENCE">证据不足</option><option value="MODEL_SIGNAL_CONFIRMED">确认模型信号候选</option><option value="LIKELY_FALSE_POSITIVE">疑似误报 · 待复核</option><option value="NEEDS_LABEL_REVIEW">需要标签复核</option></select></label>
      <ApprovalFields value={review} onChange={setReview} /><Check label="我已阅读推理与热图证据，授权保存这次具名人工反馈；不会自动确立标签真值、关闭问题或进入训练。" checked={attested} onChange={setAttested} />
      <button type="submit" disabled={!attested || !approvalReady(review)}>保存具名复核反馈</button></fieldset>
    </form>
    <section aria-label="已保存的 Normality 人工反馈"><h4>已保存的人工反馈</h4><button type="button" disabled={feedbackBusy} onClick={() => void readFeedback()}>读取人工反馈（仅 GET）</button>
      {feedbackError && <p role="alert" className="vision-models__inline-hold">{feedbackError}</p>}
      {items.map(item => <article key={item.feedback_id} className="vision-models__feedback-card"><strong>已保存并回读 · RECORDED_FOR_HUMAN_FOLLOWUP</strong><p>{item.classification} · {item.reviewer_identity}</p><p>{item.note}</p><code>{item.feedback_id}</code><Sha label="人工反馈回执 SHA-256" value={item.receipt_sha256} /><p>建议后续：{item.followup_work_item_type}；这条原始反馈本身不创建工单、关闭问题、认证标签或进入训练。真实后续以独立血缘回执为准。</p>
        {['NEEDS_LABEL_REVIEW', 'LIKELY_FALSE_POSITIVE'].includes(item.classification) && <NormalityFollowupCard scope={scope} feedback={item} inference={inference} canAct={canAct} execute={execute} />}</article>)}
    </section>
  </article>;
}

function NormalityFollowupCard({ scope, feedback, inference, canAct, execute }: { scope: VisionScope; feedback: NormalityFeedback; inference: VisionInference; canAct: boolean; execute: Execute }) {
  const [asset, setAsset] = useState<VisionInferenceAsset>(), [projection, setProjection] = useState<NormalityFollowupList>(), [importId, setImportId] = useState('');
  const [annotations, setAnnotations] = useState<NormalityFollowupAnnotations>(), [annotationId, setAnnotationId] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''); const alive = useRef(true);
  const [importReview, setImportReview] = useState<ApprovalState>({ reviewer: '', note: '' }), [importAllowed, setImportAllowed] = useState(false), [importBoundary, setImportBoundary] = useState(false);
  const [orderReview, setOrderReview] = useState<ApprovalState>({ reviewer: '', note: '' }), [assignee, setAssignee] = useState(''), [orderAllowed, setOrderAllowed] = useState(false), [evidenceRead, setEvidenceRead] = useState(false), [orderBoundary, setOrderBoundary] = useState(false);
  const valid = () => alive.current && getIdentityActorId() === scope.actorId;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const imported = projection?.imports.find(row => row.import_id === importId), manual = annotations?.annotations.filter(row => row.source === 'MANUAL') ?? [];
  const hasLinkedOrder = Boolean(imported && projection?.work_orders.some(row => row.import_id === imported.import_id));
  useEffect(() => { setAnnotationId(''); setOrderAllowed(false); setEvidenceRead(false); setOrderBoundary(false); }, [importId, annotations?.revision, annotations?.document_sha256]);
  const load = async () => {
    if (busy || !valid()) return; setBusy(true); setError(''); setAnnotations(undefined); setImportAllowed(false); setImportBoundary(false);
    try {
      const [source, state] = await Promise.all([getVisionInferenceAsset(scope, inference.asset_id), getNormalityFollowup(scope, feedback)]);
      visionEnsure(source.image_sha256 === feedback.image_sha256 && state.imports.every(row => row.vision_asset_sha256 === source.receipt_sha256 && row.image_width === source.image_width && row.image_height === source.image_height));
      if (valid()) { setAsset(source); setProjection(state); setImportId(current => state.imports.some(row => row.import_id === current) ? current : state.imports[0]?.import_id ?? ''); }
    } catch (failure) { if (valid()) { setAsset(undefined); setProjection(undefined); setError(visionErrorMessage(failure)); } }
    finally { if (valid()) setBusy(false); }
  };
  const readAnnotations = async () => {
    if (!imported || busy || !valid()) return; setBusy(true); setError(''); setAnnotations(undefined);
    try { const state = await getNormalityFollowupAnnotations(scope, imported); if (valid()) setAnnotations(state); }
    catch (failure) { if (valid()) setError(visionErrorMessage(failure)); } finally { if (valid()) setBusy(false); }
  };
  const common = { expected_feedback_sha256: feedback.receipt_sha256, expected_inference_sha256: inference.receipt_sha256, expected_asset_sha256: asset?.receipt_sha256, expected_image_sha256: feedback.image_sha256 };
  return <section className="vision-models__normality-followup"><h4>真实后续 · 导入工作簿 → 人工框 → 复核工单</h4><p>不自动生成框或标签。两步分别授权，原始反馈保持不可变；同一 request_key 只对账，不重复导入或发单。</p>
    <button type="button" disabled={busy || !canAct} onClick={() => void load()}>读取真实后续状态（仅 GET）</button>{error && <p role="alert" className="vision-models__inline-hold">{error}</p>}
    {asset && projection && projection.imports.length === 0 && <form className="vision-models__followup-import" onSubmit={event => { event.preventDefault(); if (!canAct || !importAllowed || !importBoundary || !approvalReady(importReview)) return;
      void execute(`import_normality_followup:${feedback.feedback_id}`, key => ({ ...approval(importReview, key), ...common, operator_attests_import_authorized: importAllowed, operator_attests_no_label_or_training_authority: importBoundary })); }}><h5>第一步 · 工作簿原图导入</h5><fieldset disabled={!canAct || busy}>
      <Sha label="待导入原图 SHA-256" value={asset.image_sha256} /><p>后端只读取本项目已验封 CAS 原图，并导入当前账号的真实工作簿。EXIF 非 identity 会 HOLD，需规范化为新版本重新推理。</p><ApprovalFields value={importReview} onChange={setImportReview} />
      <Check label="我授权把这条推理的已验封原图导入当前账号、项目的真实工作簿。" checked={importAllowed} onChange={setImportAllowed} /><Check label="本次导入不创建标签、不发工单、不关闭问题、不进入训练。" checked={importBoundary} onChange={setImportBoundary} />
      <button type="submit" disabled={!importAllowed || !importBoundary || !approvalReady(importReview)}>具名导入到真实工作簿</button></fieldset></form>}
    {projection && projection.imports.length > 0 && <><label>已导入血缘<select value={importId} onChange={event => { setImportId(event.target.value); setAnnotations(undefined); }}>{projection.imports.map(row => <option key={row.import_id} value={row.import_id}>{row.operator_asset_id} · {row.status}</option>)}</select></label>
      {imported && <><p>{hasLinkedOrder ? '此导入血缘已关联真实人工框和 OPEN 工单；原始导入阶段状态保持不可变。' : '原图已实际导入；尚待人工选择并保存真实框。'}{imported.coordinate_frame}</p><Sha label="导入血缘回执 SHA-256" value={imported.receipt_sha256} />
        <Link to={`/workspace?asset=${encodeURIComponent(imported.operator_asset_id)}`}>{hasLinkedOrder ? '打开真实工作簿资产' : '打开真实待标注资产'}</Link><p>{hasLinkedOrder ? '下方独立工单血缘是实际发单证据；本页不会修改已有标注。' : '请在工作簿手工标注并保存，再返回这里读取；本页不会调用标注写入。'}</p>
        <button type="button" disabled={busy} onClick={() => void readAnnotations()}>读取已保存人工框（仅 GET）</button>
        {annotations && manual.length === 0 && <p className="vision-models__inline-hold">HOLD：尚无已保存人工框；不会补造全图框或把热图当标签。</p>}
        {annotations && manual.length > 0 && <form className="vision-models__followup-order" onSubmit={event => { event.preventDefault(); if (!canAct || !annotationId || !orderAllowed || !evidenceRead || !orderBoundary || !assignee.trim() || !approvalReady(orderReview)) return;
          void execute(`create_normality_followup_work_order:${feedback.feedback_id}`, key => ({ ...approval(orderReview, key), ...common, import_id: imported.import_id, expected_import_sha256: imported.receipt_sha256,
            annotation_id: annotationId, expected_annotation_revision: annotations.revision, expected_annotation_document_sha256: annotations.document_sha256, assignee: assignee.trim(), operator_attests_create_work_order: orderAllowed, operator_attests_reviewed_evidence: evidenceRead, operator_attests_no_label_or_training_authority: orderBoundary })); }}>
          <h5>第二步 · 对已有人工框发真实工单</h5><fieldset disabled={!canAct || busy}><label>已保存人工框<select aria-label="已保存人工框" value={annotationId} onChange={event => { setAnnotationId(event.target.value); setEvidenceRead(false); setOrderAllowed(false); }}><option value="">选择已保存的 MANUAL 框</option>{manual.map(row => <option key={row.annotation_id} value={row.annotation_id}>{row.label} · {row.annotation_id}</option>)}</select></label>
          <p>当前标注版本：{annotations.revision}。{manual.find(row => row.annotation_id === annotationId) && <span>框坐标（原图归一化）：{(['x', 'y', 'width', 'height'] as const).map(key => manual.find(row => row.annotation_id === annotationId)![key].toFixed(4)).join(', ')}</span>}</p><Sha label="人工标注文档 SHA-256" value={annotations.document_sha256} />
          <label>复核工单负责人<input aria-label="复核工单负责人" value={assignee} maxLength={120} onChange={event => setAssignee(event.target.value)} /></label><ApprovalFields value={orderReview} onChange={setOrderReview} />
          <Check label="我授权为上述已有人工框创建真实 OPEN 工单，并指定负责人。" checked={orderAllowed} onChange={setOrderAllowed} /><Check label="我已复核原图、人工框与当前标注版本，确认这次发单证据。" checked={evidenceRead} onChange={setEvidenceRead} /><Check label="本次发单不修改标签、不关闭问题、不自动进入 CAPA 或训练，也不放行生产。" checked={orderBoundary} onChange={setOrderBoundary} />
          <button type="submit" disabled={!annotationId || !orderAllowed || !evidenceRead || !orderBoundary || !assignee.trim() || !approvalReady(orderReview)}>具名创建真实复核工单</button></fieldset></form>}
      </>}
    </>}
    {projection?.work_orders.map(row => <article className="vision-models__feedback-card" key={row.binding_id}><strong>真实工单已建立 · OPEN</strong><p>{row.assignee} · {row.work_order_id}</p><Sha label="工单血缘回执 SHA-256" value={row.receipt_sha256} /><Sha label="真实工单文档 SHA-256" value={row.work_order_document_sha256} /><Sha label="人工框裁剪 SHA-256" value={row.crop_sha256} /><p>绑定人工标注版本 {row.annotation_revision}；问题保持开放，未认证标签真值、未进入训练。</p></article>)}
  </section>;
}

function TttFailureDetails({ failure }: { failure: VisionTttFailure }) {
  return <article className="vision-models__details vision-models__ttt-failure"><h4>TTT 已失败关闭 · FAILED_CLOSED</h4><code>{failure.failure_id}</code>
    <p>本次 worker 未能提供可核验测量，没有分数、热图、参数变化或 guard 结果；不会伪造基线，也不会自动重试。</p>
    <dl><dt>受控失败代码</dt><dd>{failure.failure_code}</dd><dt>测量可用</dt><dd>false · NOT_MEASURED</dd><dt>重试策略</dt><dd>NEW_EXPLICIT_AUTHORIZATION_REQUIRED</dd><dt>生产放行</dt><dd>禁止 · false</dd></dl>
    <Sha label="失败回执 SHA-256" value={failure.receipt_sha256} /><Sha label="本次授权 SHA-256" value={failure.authorization_sha256} /><Sha label="TTT 实现 SHA-256" value={failure.ttt_backend_sha256} />
    <p>原 request_key 只用于 GET 对账，不重跑。若排查后仍要执行，必须在独立 TTT 表单重新确认输入、预算和全部授权，生成新的请求。</p></article>;
}
function TttReportDetails({ report }: { report: VisionTttReport }) {
  return <section className="vision-models__ttt-result"><h4>单次 TTT 测量回执</h4><strong>{report.status}</strong><p>{report.status === 'ROLLED_BACK' ? `已回滚：${report.rollback_reason}；当前分数与热图使用原模型。` : '本次学生副本通过局部 guard，当前分数与热图来自本次适应副本。'}本次接受、loss 下降不等于工业效果提升。</p>
    <p>已执行 {report.steps_completed} / {report.budget.steps} 步；结束即重置；原 pack、Backbone 与阈值保持不变；persistent_learning=false。</p>
    <dl><dt>更新前真实目标值</dt><dd>{report.objective_before === null ? 'NOT_MEASURED' : report.objective_before.toFixed(6)}</dd><dt>最后一次更新后重算目标值</dt><dd>{report.objective_after === null ? 'NOT_MEASURED' : report.objective_after.toFixed(6)}</dd></dl><p>下面 loss 曲线在每步更新前测量，不冒充最终候选目标值；接受还要求最终目标严格下降和独立 guard 通过。</p>
    <Sha label="适应前参数 SHA-256" value={report.parameter_sha256_before} /><Sha label="尝试后参数 SHA-256" value={report.attempted_parameter_sha256} /><Sha label="实际生效参数 SHA-256" value={report.effective_parameter_sha256} />
    <div className="vision-models__table"><table><caption>独立人工 guard · 非工业效果评测</caption><thead><tr><th>阶段</th><th>TP</th><th>TN</th><th>FP</th><th>FN</th></tr></thead><tbody>{([['适应前', report.guard_before], ['尝试后', report.guard_after], ['实际生效', report.effective_guard]] as const).map(([label, matrix]) => <tr key={label}><th>{label}</th>{matrix ? <><td>{matrix.tp}</td><td>{matrix.tn}</td><td>{matrix.fp}</td><td>{matrix.fn}</td></> : <td colSpan={4}>NOT_MEASURED</td>}</tr>)}</tbody></table></div>
    <div className="vision-models__table"><table><caption>实际优化损失</caption><thead><tr><th>步数</th><th>总 loss</th><th>重建</th><th>Replay</th><th>参数锚定</th></tr></thead><tbody>{report.loss_curve.map(row => <tr key={row.step}><th>{row.step}</th><td>{row.loss.toFixed(6)}</td><td>{row.reconstruction_loss.toFixed(6)}</td><td>{row.replay_loss.toFixed(6)}</td><td>{row.anchor_loss.toFixed(6)}</td></tr>)}</tbody></table></div></section>;
}

function RecordDetails({ record, scope, canAct, execute, feedback, onFeedback }: { record: VisionRecord; scope: VisionScope; canAct: boolean; execute: Execute; feedback: VisionFeedback[]; onFeedback: (runId: string, items: VisionFeedback[]) => void }) {
  return <article className="vision-models__details"><h4>已验封详情</h4><code>{record.resource_id}</code><Sha label="记录回执 SHA-256" value={record.receipt_sha256} />
    <dl><dt>项目</dt><dd>{record.project_id}</dd><dt>当前状态</dt><dd>{record.status}</dd><dt>生产放行</dt><dd>禁止 · false</dd></dl>
    {'model_id' in record && 'task_type' in record && record.task_type !== 'normality' && <><Sha label="权重 SHA-256" value={record.weights_sha256} /><dl><dt>文件字节数</dt><dd>{record.file_bytes.toLocaleString()}</dd><dt>任务 / 格式</dt><dd>{record.task_type} / {record.format}</dd><dt>许可声明</dt><dd>{record.license_id}</dd><dt>已加载</dt><dd>否；登记不等于加载授权</dd></dl></>}
    {'runtime_id' in record && 'probe' in record && <><Sha label="运行环境指纹" value={record.runtime_sha256} />{record.probe.status === 'failed'
      ? <><p className="vision-models__inline-hold">导入失败 · UNAVAILABLE。Python 与依赖版本为 NOT_MEASURED，不继承旧 metadata 或视为 PASSED；本环境不能用于训练或 TTT。</p><dl><dt>受控失败代码</dt><dd>{record.probe.error_code}</dd><dt>受控错误类型</dt><dd>{record.probe.error_type}</dd></dl></>
      : <dl><dt>Python</dt><dd>{record.probe.python_version.join('.')}</dd>{Object.entries(record.probe.packages).map(([name, version]) => <div className="vision-models__kv" key={name}><dt>{name}</dt><dd>{version ?? '未安装'}</dd></div>)}<dt>实际导入检查</dt><dd>{record.probe.import_status}</dd></dl>}<ProbeForm runtime={record} canAct={canAct} execute={execute} /></>}
    {'dataset_receipt' in record && <><Sha label="数据冻结回执 SHA-256" value={record.dataset_receipt_sha256} /><div className="vision-models__splits">{Object.entries(record.dataset_receipt.split_counts).map(([split, count]) => <span key={split}>{split}<b>{count}</b></span>)}</div><p>固定 {record.dataset_receipt.class_names.length} 个类别。验证 / 测试样本不回灌训练。</p>
      {record.pool_binding && <><Sha label="来源池绑定回执 SHA-256" value={record.pool_binding.receipt_sha256} /><code>{record.pool_binding.pool_id} · {record.pool_binding.version_id}</code><p>已绑定原始标注坐标系与来源版本；再次训练仍重新核验池、快照和标注。不是独立标签真值认证。</p></>}</>}
    {'training' in record && <><RunDetails run={record} canAct={canAct} execute={execute} /><FeedbackPanel run={record} scope={scope} canAct={canAct} execute={execute} feedback={feedback.filter(item => item.run_id === record.run_id)} onFeedback={onFeedback} /></>}
  </article>;
}

function ProbeForm({ runtime, canAct, execute }: { runtime: VisionRuntime; canAct: boolean; execute: Execute }) {
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }); const [trusted, setTrusted] = useState(false), [authorized, setAuthorized] = useState(false), [importCheck, setImportCheck] = useState(false);
  return <form onSubmit={event => { event.preventDefault(); void execute(`probe_runtime:${runtime.runtime_id}`, key => ({ ...approval(review, key), expected_runtime_sha256: runtime.runtime_sha256, operator_attests_trusted_runtime: trusted, operator_attests_execution_authorized: authorized, import_check: importCheck })); }}>
    <h4>显式复查此运行环境</h4><fieldset disabled={!canAct}><ApprovalFields value={review} onChange={setReview} />
      <Check label="我确认此登记环境可信。" checked={trusted} onChange={setTrusted} /><Check label="我授权本次执行环境探测。" checked={authorized} onChange={setAuthorized} />
      <Check label="额外授权真实导入 torch / torchvision / ultralytics 并进行 CPU 探测（不训练）。" checked={importCheck} onChange={setImportCheck} />
      <button type="submit" disabled={!trusted || !authorized || !approvalReady(review)}>{importCheck ? '执行真实库导入与 CPU 探测' : '只复查环境元数据'}</button></fieldset></form>;
}

function RunDetails({ run, canAct, execute }: { run: VisionRun; canAct: boolean; execute: Execute }) {
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }); const [reviewed, setReviewed] = useState(false);
  const active = ['QUEUED', 'RUNNING'].includes(run.status), candidate = run.status === 'SUCCEEDED_CANDIDATE' && run.selection === 'PENDING';
  const result = run.result; const metrics = [...new Set([...Object.keys(result?.baseline ?? {}), ...Object.keys(result?.candidate ?? {})])];
  const action = (name: 'cancel' | 'recover' | 'selection', choice?: 'APPROVE_SANDBOX' | 'REJECT') => {
    void execute(`${name}:${run.run_id}`, key => ({ ...approval(review, key), expected_run_sha256: run.receipt_sha256, operator_attests_reviewed: reviewed,
      ...(name === 'selection' ? { action: choice, expected_candidate_weights_sha256: result?.checkpoint?.sha256 } : {}) }));
  };
  return <><p className="vision-models__inline-hold">{visionStatusLabel(run.status)}。候选完成只证明执行和权重持久化；指标为 0 也可能正常完成，不自动代表精度通过。</p>
    <dl><dt>初始化</dt><dd>{run.initialization === 'ARCHITECTURE_RANDOM' ? '架构随机初始化 · 非预训练' : '已登记本地权重 · 来源声明未自动认证'}</dd><dt>执行设备</dt><dd>CPU；GPU_NOT_RUN</dd><dt>候选选择</dt><dd>{run.selection}</dd><dt>取消请求</dt><dd>{run.cancel_requested ? '已申请；以服务端终态为准' : '未申请'}</dd><dt>测试集</dt><dd>NOT_RUN · 不回灌训练</dd></dl>
    <Sha label="运行环境指纹" value={run.runtime_sha256} /><Sha label="数据集回执" value={run.dataset_receipt_sha256} />
    {result?.checkpoint && <Sha label="候选权重 SHA-256" value={result.checkpoint.sha256} />}
    {metrics.length > 0 && <div className="vision-models__table"><table><caption>验证集指标 · 没有工业达标判定</caption><thead><tr><th>指标</th><th>基线</th><th>候选</th></tr></thead><tbody>{metrics.map(name => <tr key={name}><th>{name}</th><td>{result?.baseline?.[name]?.toFixed(5) ?? '未测'}</td><td>{result?.candidate?.[name]?.toFixed(5) ?? '未测'}</td></tr>)}</tbody></table></div>}
    {result?.actual_epochs !== undefined && <p>实际 {result.actual_epochs} 轮 · train {result.training_samples} 个 · val {result.validation_samples} 个。</p>}
    {Boolean(run.responds_to_feedback_ids?.length) && <p>本轮关联 {run.responds_to_feedback_ids!.length} 个已复核反馈；关联不是问题关闭证明。</p>}
    {run.error_code && <p className="vision-models__inline-hold">服务端记录了受控失败或中断。请保留运行 ID 核查；本页不展示原始异常、路径或执行日志。</p>}
    {(active || candidate) && <form onSubmit={event => event.preventDefault()}><fieldset disabled={!canAct}><ApprovalFields value={review} onChange={setReview} /><Check label="我已阅读当前运行回执并确认本次处置；只针对这个 SHA 版本。" checked={reviewed} onChange={setReviewed} />
      <div className="vision-models__actions">{active && <><button type="button" disabled={!reviewed || !approvalReady(review) || run.cancel_requested} onClick={() => action('cancel')}>申请取消本次训练</button><button type="button" disabled={!reviewed || !approvalReady(review)} onClick={() => action('recover')}>核查执行归属并记录中断</button></>}
        {candidate && <><button type="button" disabled={!reviewed || !approvalReady(review)} onClick={() => action('selection', 'APPROVE_SANDBOX')}>人工选用候选（仅沙箱）</button><button type="button" disabled={!reviewed || !approvalReady(review)} onClick={() => action('selection', 'REJECT')}>拒绝候选</button></>}</div>
      {active && <small>恢复只在执行锁释放后记录 INTERRUPTED_HOLD；不重跑。仍在执行的任务会由后端拒绝此操作。</small>}</fieldset></form>}
  </>;
}

function FeedbackPanel({ run, scope, canAct, execute, feedback, onFeedback }: { run: VisionRun; scope: VisionScope; canAct: boolean; execute: Execute; feedback: VisionFeedback[]; onFeedback: (runId: string, items: VisionFeedback[]) => void }) {
  const [loading, setLoading] = useState(false), [loaded, setLoaded] = useState(false), [error, setError] = useState('');
  const mounted = useRef(true); useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const load = async () => {
    if (loading) return; setLoading(true); setError(''); setLoaded(false);
    try { const items = await getVisionFeedback(scope, run); if (mounted.current && getIdentityActorId() === scope.actorId) { onFeedback(run.run_id, items); setLoaded(true); } }
    catch (failure) { if (mounted.current) setError(visionErrorMessage(failure)); }
    finally { if (mounted.current) setLoading(false); }
  };
  return <section className="vision-models__feedback"><h4>验证集错误候选与人工复核</h4>
    <p>固定 confidence ≥ 0.25、IoU ≥ 0.5、同类别贪心匹配。FP / FN 表示与参考标签不一致，不是标签错误判决，也不是总体 mAP。</p>
    <p>反馈状态：{run.feedback_status ?? 'NOT_AVAILABLE_LEGACY_RESULT'}</p>
    <button type="button" disabled={loading} onClick={() => void load()}>读取本轮验证反馈（仅 GET）</button>
    {error && <p className="vision-models__inline-hold" role="alert">{error}</p>}
    {loaded && feedback.length === 0 && <p>{run.feedback_status === 'NO_VAL_DISAGREEMENT_AT_FIXED_PROTOCOL' ? '当前固定协议下未产生 FP / FN 候选；这不代表标签真值已确认或工业效果达标。' : '当前没有可读取的错误候选；可能尚未评测或是旧回执，不能解释为零错误。'}</p>}
    {feedback.map(item => <FeedbackCard key={item.receipt_sha256} item={item} run={run} canAct={canAct} execute={execute} />)}
  </section>;
}
function FeedbackCard({ item, run, canAct, execute }: { item: VisionFeedback; run: VisionRun; canAct: boolean; execute: Execute }) {
  const [review, setReview] = useState<ApprovalState>({ reviewer: '', note: '' }), [attested, setAttested] = useState(false);
  const [classification, setClassification] = useState<VisionFeedbackClassification>('UNKNOWN');
  return <article className="vision-models__feedback-card"><strong>{item.sample_id} · val</strong><code>{item.feedback_id}</code>
    <div className="vision-models__splits"><span>匹配 TP<b>{item.detail.tp}</b></span><span>误检候选 FP<b>{item.detail.fp}</b></span><span>漏检候选 FN<b>{item.detail.fn}</b></span></div>
    <p>匹配 IoU：{item.detail.matched_ious.length ? item.detail.matched_ious.map(value => value.toFixed(3)).join('、') : '没有匹配框'}。问题尚未关闭；参考标签并未获得独立真值认证。</p>
    <Sha label="反馈回执 SHA-256" value={item.receipt_sha256} /><Sha label="来源图像 SHA-256" value={item.image_sha256} />
    <details><summary>查看预测 / 参考框数值</summary><div className="vision-models__table"><table><thead><tr><th>来源</th><th>类 ID</th><th>xyxy（归一化）</th><th>置信度</th></tr></thead><tbody>
      {[...item.detail.prediction_boxes.map(box => ({ box, source: '预测' })), ...item.detail.ground_truth_boxes.map(box => ({ box, source: '参考标签' }))].map(({ box, source }, index) => <tr key={index}><td>{source}</td><td>{box.class_id}</td><td>{box.xyxy.map(value => value.toFixed(3)).join(', ')}</td><td>{box.confidence?.toFixed(3) ?? '不适用'}</td></tr>)}
    </tbody></table></div></details>
    {item.status === 'PENDING_HUMAN_REVIEW' ? <form onSubmit={event => { event.preventDefault(); void execute(`triage_feedback:${item.feedback_id}`, key => ({ ...approval(review, key), expected_run_sha256: run.receipt_sha256,
      expected_feedback_sha256: item.receipt_sha256, operator_attests_reviewed: attested, classification }), { runId: run.run_id }); }}><fieldset disabled={!canAct}>
      <label>人工反馈分类<select aria-label="人工反馈分类" value={classification} onChange={e => { setClassification(e.target.value as VisionFeedbackClassification); setAttested(false); }}><option value="UNKNOWN">未知 · 证据不足</option><option value="MODEL_ERROR">模型问题候选（人工裁定）</option><option value="LABEL_REVIEW_REQUIRED">标签复核候选（尚未确认错误）</option><option value="HARD_SAMPLE">困难样本候选（人工裁定）</option></select></label>
      <ApprovalFields value={review} onChange={setReview} /><Check label="我已复核预测与参考标签证据，明确记录上述分类；不自动关闭问题，也不授权回灌验证样本。" checked={attested} onChange={setAttested} />
      <button type="submit" disabled={!attested || !approvalReady(review)}>记录人工反馈分类</button>
    </fieldset></form> : <p>已人工分类：{item.classification} · TRIAGED_FOR_REVIEW。请在左侧新轮次中明确选择该反馈和新数据版本；UNKNOWN 不可用于关联。</p>}
  </article>;
}
