import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cpu, Database, FileCheck2, RefreshCw, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { useProduct } from '../ProductContext';
import { getIdentityActorId } from '../identitySession.ts';
import { getVisionCapabilities, listVisionRecords, getVisionRun, getVisionModel, getVisionOperation, getVisionFeedback,
  getVisionPool, prepareVisionMutation, sendVisionMutation, visionWriteKnownRejected, visionErrorMessage } from '../data/visionModelApi.ts';
import { parseDetectionManifest, parseVisionPending, visionPendingStorageKey, visionStatusLabel } from '../visionModelDomain.ts';
import type { VisionScope, VisionPending, VisionMutationOperation, VisionRecord, VisionModel, VisionRuntime, VisionDataset, VisionRun,
  VisionCapabilities, VisionApproval, VisionBudget, DetectionManifest, CreateVisionRunRequest, VisionFeedback, VisionFeedbackClassification } from '../visionModelDomain.ts';
import type { DataPoolProjection } from '../dataPoolDomain.ts';
import '../styles/vision-models.css';

type Tab = 'runtime' | 'model' | 'dataset' | 'run';
type Execute = (operation: VisionMutationOperation, request: (key: string) => unknown, context?: { runId: string }) => Promise<boolean>;
interface ApprovalState { reviewer: string; note: string }
const tabs: { id: Tab; title: string; icon: typeof Cpu }[] = [
  { id: 'runtime', title: '运行环境', icon: Cpu }, { id: 'model', title: '权重', icon: FileCheck2 },
  { id: 'dataset', title: '数据', icon: Database }, { id: 'run', title: '训练', icon: SlidersHorizontal },
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
  const [feedback, setFeedback] = useState<VisionFeedback[]>([]);
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
      const [c, m, r, d, tr] = await Promise.all([getVisionCapabilities(scope), listVisionRecords(scope, 'model'), listVisionRecords(scope, 'runtime'), listVisionRecords(scope, 'dataset'), listVisionRecords(scope, 'run')]);
      if (!validScope()) return;
      // Counts are advisory; concurrent training may add a candidate between GETs.
      setCapabilities(c); setModels(m); setRuntimes(r); setDatasets(d); setRuns(tr);
      const chosen = selectedRef.current;
      if (chosen) setSelected([...m, ...r, ...d, ...tr].find(item => item.resource_id === chosen.resource_id));
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
      clearLock(pending); success = true;
      if (validScope()) {
        if ('feedback_id' in result) setFeedback(current => [...current.filter(item => item.feedback_id !== result.feedback_id), result]);
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
      clearLock(pending);
      if ('feedback_id' in receipt.resource) {
        const item = receipt.resource; setFeedback(current => [...current.filter(row => row.feedback_id !== item.feedback_id), item]);
        setSelected(await getVisionRun(scope, item.run_id));
      } else setSelected(receipt.resource);
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
      const next = 'run_id' in record ? await getVisionRun(scope, record.run_id) : 'model_id' in record ? await getVisionModel(scope, record.model_id) : record;
      if (validScope()) setSelected(next);
    } catch (failure) { if (validScope()) { setFresh(false); setError(visionErrorMessage(failure)); } }
    finally { if (validScope()) setBusy(false); }
  };
  const canAct = fresh && Boolean(capabilities) && !busy && !lock.pending && !lock.corrupt;
  const records = { runtime: runtimes, model: models, dataset: datasets, run: runs }[tab];
  return <section className="vision-models" aria-label="本地视觉模型工作台">
    <header className="vision-models__header"><div><p>LOCAL VISION / {projectName}</p><h2>把模型放进可复核的训练流程</h2><span>权重、数据与运行环境各自绑定 SHA-256。每次执行都需要独立授权。</span></div>
      <button type="button" onClick={() => void refresh()} disabled={busy}><RefreshCw size={15} />刷新状态（仅 GET）</button></header>
    <div className="vision-models__boundary"><ShieldCheck size={18} /><p><strong>当前执行边界：CPU · YOLO26n detect · 有界监督训练</strong><span>不自动下载权重、不外发数据；GPU 未运行；TTT 关闭（未实现）；工业效果 NOT_EVALUATED；不接生产。</span></p></div>
    {error && <div className="vision-models__alert" role="alert">{error}</div>}
    {notice && <div className="vision-models__notice" role="status">{notice}</div>}
    {lock.corrupt && <div className="vision-models__alert" role="alert">HOLD：本浏览器对账锁无法读取或存储不可用。所有写入已阻止；请先通过服务端操作记录核查，不要通过清除锁来重跑训练。</div>}
    {lock.pending && <div className="vision-models__alert" role="status"><strong>写入结果待确认 · UNKNOWN</strong><p>只保存当前账号与项目的操作名和请求标识。关页后保留，不保存路径、复核说明或令牌。</p><code>{lock.pending.operation} · {lock.pending.requestKey}</code>
      <button type="button" onClick={() => void reconcile()} disabled={busy}>使用原 request_key 仅 GET 对账</button></div>}
    <nav className="vision-models__tabs" aria-label="视觉模型流程">{tabs.map(({ id, title, icon: Icon }) => <button type="button" key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => { setTab(id); setSelected(undefined); }}><Icon size={16} />{title}<span>{({ runtime: runtimes, model: models, dataset: datasets, run: runs }[id]).length}</span></button>)}</nav>
    <div className="vision-models__layout"><div className="vision-models__form-panel">
      {tab === 'runtime' && <RuntimeForm canAct={canAct} execute={execute} />}
      {tab === 'model' && <ModelForm canAct={canAct} execute={execute} />}
      {tab === 'dataset' && <>{poolId ? <><PoolDatasetForm key={`${poolId}:${params.get('version') ?? ''}`} scope={scope} poolId={poolId} expectedVersionId={params.get('version')} canAct={canAct} execute={execute} />
        <details className="vision-models__external"><summary>也可登记外部检测 JSON 清单</summary><DatasetForm canAct={canAct} execute={execute} /></details></> : <DatasetForm canAct={canAct} execute={execute} />}</>}
      {tab === 'run' && <TrainingForm canAct={canAct} execute={execute} runtimes={runtimes} datasets={datasets} models={models} feedback={feedback} activeRun={runs.some(run => ['QUEUED', 'RUNNING'].includes(run.status))} />}
    </div><div className="vision-models__records"><h3>{tabs.find(item => item.id === tab)?.title}记录</h3>
      {!records.length && <Empty>{fresh ? '当前项目还没有记录。登记完成后才能在下一阶段选择。' : '尚未读取到可验证记录；不会显示虚构样例。'}</Empty>}
      {records.map(record => <button className="vision-models__record" type="button" key={record.resource_id} disabled={busy} onClick={() => void details(record)} aria-pressed={selected?.resource_id === record.resource_id}>
        <strong>{'display_name' in record ? record.display_name : 'run_id' in record ? visionStatusLabel(record.status) : record.dataset_receipt.source_version}</strong>
        <code>{record.resource_id}</code><span>{record.status}</span>{'runtime_id' in record && !('run_id' in record) && <small>库导入：{record.probe.import_status}</small>}
      </button>)}
      {selected && <RecordDetails key={selected.receipt_sha256} record={selected} scope={scope} canAct={canAct} execute={execute} feedback={feedback} onFeedback={(runId, items) => setFeedback(current => [...current.filter(row => row.run_id !== runId), ...items])} />}
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

function RecordDetails({ record, scope, canAct, execute, feedback, onFeedback }: { record: VisionRecord; scope: VisionScope; canAct: boolean; execute: Execute; feedback: VisionFeedback[]; onFeedback: (runId: string, items: VisionFeedback[]) => void }) {
  return <article className="vision-models__details"><h4>已验封详情</h4><code>{record.resource_id}</code><Sha label="记录回执 SHA-256" value={record.receipt_sha256} />
    <dl><dt>项目</dt><dd>{record.project_id}</dd><dt>当前状态</dt><dd>{record.status}</dd><dt>生产放行</dt><dd>禁止 · false</dd></dl>
    {'model_id' in record && <><Sha label="权重 SHA-256" value={record.weights_sha256} /><dl><dt>文件字节数</dt><dd>{record.file_bytes.toLocaleString()}</dd><dt>任务 / 格式</dt><dd>{record.task_type} / {record.format}</dd><dt>许可声明</dt><dd>{record.license_id}</dd><dt>已加载</dt><dd>否；登记不等于加载授权</dd></dl></>}
    {'runtime_id' in record && !('run_id' in record) && <><Sha label="运行环境指纹" value={record.runtime_sha256} /><dl><dt>Python</dt><dd>{record.probe.python_version.join('.')}</dd>{Object.entries(record.probe.packages).map(([name, version]) => <div className="vision-models__kv" key={name}><dt>{name}</dt><dd>{version ?? '未安装'}</dd></div>)}<dt>实际导入检查</dt><dd>{record.probe.import_status}</dd></dl><ProbeForm runtime={record} canAct={canAct} execute={execute} /></>}
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
      <label>人工反馈分类<select aria-label="人工反馈分类" value={classification} onChange={e => { setClassification(e.target.value as VisionFeedbackClassification); setAttested(false); }}><option value="UNKNOWN">未知 · 证据不足</option><option value="MODEL_ERROR">模型问题（人工判断）</option><option value="LABEL_REVIEW_REQUIRED">标签需要复核（未确认错误）</option><option value="HARD_SAMPLE">困难样本（人工判断）</option></select></label>
      <ApprovalFields value={review} onChange={setReview} /><Check label="我已复核预测与参考标签证据，明确记录上述分类；不自动关闭问题，也不授权回灌验证样本。" checked={attested} onChange={setAttested} />
      <button type="submit" disabled={!attested || !approvalReady(review)}>记录人工反馈分类</button>
    </fieldset></form> : <p>已人工分类：{item.classification} · TRIAGED_FOR_REVIEW。请在左侧新轮次中明确选择该反馈和新数据版本；UNKNOWN 不可用于关联。</p>}
  </article>;
}
