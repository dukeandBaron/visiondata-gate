import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, GitBranch, RefreshCw, ShieldCheck } from "lucide-react";
import { useProduct } from "../ProductContext";
import { getTaskVisualEvidence, listAgentTasks, loadTaskVisualEvidencePreview, loadTaskVisualEvidenceMask, OperatorApiError } from "../data/api";
import { getComputePreflight, type ComputePreflight } from "../data/computeApi";
import {
  createLearningCycle, getLearningCycle, getLearningRun, learningCycleAction,
  listLearningCycles, reviewLearningFeedback, runLearningRound, selectLearningModel,
  getLearningOperation, getLearningReadiness, linkLearningFeedback,
} from "../data/learningApi";
import type { LearningCycle, LearningEvaluation, LearningFeedback, LearningRun, LearningScope, LearningReadiness, NormalMaskAttestation, LearningOperationKind } from "../learningDomain";
import type { AgentTask } from "../agentDomain";
import type { TaskVisualEvidenceManifest } from "../visualEvidenceDomain";
import "../styles/learning-loop.css";

const states: Record<string, string> = {
  READY: "已冻结，等待启动", RUNNING: "本地计算中", AWAITING_REVIEW: "等待人工复核",
  AWAITING_DATA: "等待下一版训练数据", HOLD_REQUIRES_NEW_PROTOCOL: "需重建评估协议",
  STOPPED: "已停止", FINALIZING: "最终测试中", FINALIZED: "最终测试已封存",
  COMPLETED: "本轮计算完成", FAILED: "本轮失败", CANCELLED: "已取消", INTERRUPTED: "运行中断",
};
const classifications = {
  LABEL_ERROR: ["人工确认的标签问题", "修订标注后建立新评估协议；不能在旧验证集上继续择优。"],
  HARD_SAMPLE: ["困难样本候选（人工裁定）", "保留当前验证样本，另行采集类似的训练样本。"],
  DISTRIBUTION_SHIFT: ["分布变化候选（人工裁定）", "补采具有代表性的训练数据，不移动验证集或测试集。"],
  INSUFFICIENT_EVIDENCE: ["证据不足", "暂停当前协议并补证，不将样本直接归为坏数据。"],
} as const;
type Classification = keyof typeof classifications;
type PendingWrite = { key: string; operation: string; cycleId?: string; runId?: string; taskId?: string; feedbackId?: string };
type Execute = (operation: string, run: (key: string) => Promise<unknown>, ids?: Partial<PendingWrite>) => Promise<void>;
const short = (value: string) => value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
const metric = (value: number | null | undefined) => value == null ? "未测得" : value.toFixed(4);
const message = (error: unknown) => error instanceof Error ? error.message : "读取失败，请恢复连接后重试。";
function readPending(storageKey: string): PendingWrite | null {
  try {
    const stored = localStorage.getItem(storageKey);
    if (!stored) return null;
    const value: unknown = JSON.parse(stored);
    if (!value || typeof value !== "object" || !("key" in value) || typeof value.key !== "string" || !("operation" in value) || typeof value.operation !== "string") throw new Error("Invalid pending operation");
    return value as PendingWrite;
  } catch { return { key: "unreadable-local-lock", operation: "UNKNOWN" }; }
}

export function LearningLoopPage() {
  const { activeWorkspace, activeProject } = useProduct();
  const workspaceId = activeWorkspace?.workspace_id, projectId = activeProject?.project_id;
  const scope = useMemo(() => workspaceId && projectId ? { workspaceId, projectId } : null, [workspaceId, projectId]);
  if (!scope || !activeProject) return <section className="learning-page"><h1>数据处置与学习闭环</h1><p>请先在左侧选择工作空间和项目。</p></section>;
  return <LearningWorkbench key={`${scope.workspaceId}:${scope.projectId}`} scope={scope} projectName={activeProject.name} />;
}

function LearningWorkbench({ scope, projectName }: { scope: LearningScope; projectName: string }) {
  const [params, setParams] = useSearchParams();
  const cycleId = params.get("cycle") ?? "";
  const [cycles, setCycles] = useState<LearningCycle[]>([]);
  const [cycle, setCycle] = useState<LearningCycle | null>(null);
  const [runs, setRuns] = useState<LearningRun[]>([]);
  const [fresh, setFresh] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const storageKey = `learning:pending:${scope.workspaceId}:${scope.projectId}`;
  const [pending, setPending] = useState<PendingWrite | null>(() => readPending(storageKey));
  const mounted = useRef(true), requestVersion = useRef(0), writing = useRef(false);
  const pendingRef = useRef(pending); pendingRef.current = pending;
  const cycleRef = useRef(cycleId); cycleRef.current = cycleId;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; requestVersion.current++; }; }, []);
  useEffect(() => {
    const changed = (event: StorageEvent) => { if (event.key === storageKey || event.key === null) { setPending(readPending(storageKey)); setFresh(false); } };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, [storageKey]);

  const refresh = useCallback(async (reconcile = false) => {
    const version = ++requestVersion.current;
    setBusy(true); setFresh(false); setError("");
    try {
      const list = await listLearningCycles(scope);
      let selected: LearningCycle | null = null;
      let records: LearningRun[] = [];
      if (cycleId) {
        selected = await getLearningCycle(scope, cycleId);
        records = await Promise.all(selected.round_ids.map(id => getLearningRun(scope, cycleId, id)));
        // Mixed revisions must not authorize an action while another reviewer writes.
        const confirmed = await getLearningCycle(scope, cycleId);
        if (confirmed.receipt_sha256 !== selected.receipt_sha256) throw new Error("复核期间周期发生变化，请刷新以读取一致版本。");
      }
      if (!mounted.current || version !== requestVersion.current) return;
      setCycles(list); setCycle(selected); setRuns(records); setFresh(true);
      if (reconcile && pendingRef.current) {
        const lock = pendingRef.current;
        let found = false, waiting = false;
        const operation = ({ round: "train", selection: "select" } as Record<string, string>)[lock.operation] ?? lock.operation;
        const target = lock.operation === "create" ? lock.taskId : ["feedback", "followup"].includes(lock.operation) ? lock.feedbackId : lock.operation === "selection" ? lock.runId : lock.cycleId;
        if (target) {
          const result = await getLearningOperation(scope, operation as LearningOperationKind, lock.key, target);
          if (!mounted.current || version !== requestVersion.current) return;
          found = result.lookup_status === "FOUND" && result.execution_status === "RESULT_AVAILABLE";
          waiting = result.lookup_status === "FOUND" && result.execution_status === "PENDING";
        } else {
          // Compatibility for old local keys that predate the scoped operation endpoint.
          if (lock.operation === "create") found = list.some(item => item.request.request_key === lock.key && item.dataset.binding.task_id === lock.taskId);
          if (lock.operation === "round" && lock.cycleId === selected?.cycle_id) found = records.some(item => item.approval.request_key === lock.key);
        }
        if (found) {
          localStorage.removeItem(storageKey); setPending(null);
          setFresh(false);
          setNotice("已通过 GET 找到原请求回执，未重放写入。请再刷新周期与反馈以核验最新一致版本，然后继续。");
        } else setNotice(waiting ? "原请求已找到，服务端仍在执行。请稍后继续 GET 对账，不重放请求。" : "已刷新服务端事实，但尚未找到原请求的唯一对账凭据。保留 HOLD，不重复写入。");
      }
    } catch (caught) {
      if (mounted.current && version === requestVersion.current) { setFresh(false); setError(message(caught)); }
    } finally { if (mounted.current && version === requestVersion.current) setBusy(false); }
  }, [scope, cycleId, storageKey]);
  // Scope object is stable for this keyed workbench instance.
  useEffect(() => { setCycle(null); setRuns([]); void refresh(); }, [refresh]);

  const executeLocked: Execute = async (operation, action, ids = {}) => {
    if (!fresh || busy || writing.current || pendingRef.current) return;
    const existing = readPending(storageKey);
    if (existing) { setPending(existing); setFresh(false); return; }
    const lock: PendingWrite = { key: crypto.randomUUID(), operation, cycleId: cycleId || undefined, ...ids };
    // Persist the identity BEFORE sending. Leaving/reloading the page cannot remove the guard.
    try { localStorage.setItem(storageKey, JSON.stringify(lock)); }
    catch { setError("浏览器无法保存待对账标识，操作未发送。请启用本地持久存储后再试。"); return; }
    writing.current = true; setBusy(true); setPending(lock); setError(""); setNotice("");
    try {
      await action(lock.key);
      localStorage.removeItem(storageKey);
      if (!mounted.current) return;
      setPending(null); pendingRef.current = null;
      setNotice("操作回执已核验。正在刷新实际状态；该操作不授予生产放行权。");
      if (cycleRef.current === cycleId) await refresh();
    } catch (caught) {
      // Only explicit backend rejections prove the write was refused. Local validation
      // failures, timeouts, invalid receipts and 5xx remain ambiguous after dispatch.
      const refused = caught instanceof OperatorApiError && [400, 401, 403, 404, 409, 422].includes(caught.status)
        && caught.code !== "LEARNING_CONTRACT_HOLD";
      if (refused) localStorage.removeItem(storageKey);
      if (!mounted.current) return;
      setFresh(false); setError(message(caught));
      if (refused) { setPending(null); pendingRef.current = null; }
    } finally { writing.current = false; if (mounted.current) setBusy(false); }
  };
  const execute: Execute = async (operation, action, ids) => {
    if (!navigator.locks) { setError("当前浏览器无法保证多窗口写入互斥，请使用本地最新版桌面浏览器；操作未发送。"); return; }
    await navigator.locks.request(`${storageKey}:writer`, { mode: "exclusive", ifAvailable: true }, async lock => {
      if (!lock) { setError("同一浏览器的另一窗口正在处理本项目写入，请稍后 GET 对账。"); return; }
      await executeLocked(operation, action, ids);
    });
  };

  const current = cycle?.cycle_id === cycleId ? cycle : null;
  const latest = current ? runs.find(item => item.run_id === current.round_ids.at(-1)) : undefined;
  const canAct = fresh && !busy && !pending;
  return <div className="learning-page" aria-busy={busy}>
    <header className="learning-header"><div><span><GitBranch size={16} /> {projectName} · 本地学习工作流</span><h1>数据处置与学习闭环</h1><p>先分清数据问题与模型难例，再决定返修、补采或继续验证。</p></div>
      <button onClick={() => void refresh(Boolean(pending))} disabled={busy}><RefreshCw size={15} />{pending ? "仅 GET 对账" : "刷新周期与反馈"}</button></header>
    <div className="learning-boundary"><ShieldCheck size={17} /><span>当前接入：本地 API · CPU 参考模型沙箱。不是工厂在线连接，也不是昇腾 / CANN 调度；不自动修改原图、移动验证集或批准生产发布。</span></div>
    {error && <p role="alert" className="learning-alert">STALE_HOLD · {error} 上次结果仅供查看，不再授权操作。</p>}
    {pending && <div role="status" className="learning-alert"><strong>写入结果待对账</strong><p>请求 {pending.key} · {pending.operation}。此浏览器中本项目的后续写入已锁定，关页后仍保留；只能显式 GET 对账，不能自动重试。跨浏览器仍以服务端合同为准。</p></div>}
    {notice && <p role="status" className="learning-notice">{notice}</p>}
    <div className="learning-layout">
      <aside className="learning-index"><h2>学习周期</h2><button disabled={busy} onClick={() => setParams(current => { const next = new URLSearchParams(current); next.delete("cycle"); return next; })}>从已复核任务开始</button>
        {cycles.map(item => <button key={item.cycle_id} data-testid={`cycle-${item.cycle_id}`} aria-pressed={cycleId === item.cycle_id} disabled={busy}
          onClick={() => { setFresh(false); setParams(current => { const next = new URLSearchParams(current); next.set("cycle", item.cycle_id); return next; }); }}>
          <strong>{short(item.cycle_id)}</strong><span>{fresh ? states[item.status] : "上次读取 · 待刷新"}</span><small>{item.round_ids.length} 轮 · {item.dataset.samples.length} 个冻结样本</small></button>)}
        {fresh && !cycles.length && <p>当前项目还没有学习周期。先完成真实数据导入、逐样本复核和五类检查。</p>}
        <Link to="/workspace?purpose=annotation-rework">打开标注工作簿</Link><Link to="/capa">查看整改工单</Link>
      </aside>
      <main className="learning-main">
        {!cycleId && <LearningInput scope={scope} initialTask={params.get("task") ?? ""} canAct={canAct} execute={execute} />}
        {cycleId && !current && <p role="status">{busy ? "正在读取冻结成员与轮次回执…" : "尚未核验此周期。请刷新或从左侧选择本项目的周期。"}</p>}
        {current && <>
          <section className="learning-lineage" aria-label="真实数据与模型血缘">
            <div><small>冻结数据版本</small><strong>{short(current.dataset.dataset_id)}</strong><Link to={`/command-center?task=${encodeURIComponent(current.dataset.binding.task_id)}`}>查看来源任务</Link></div><ArrowRight size={18} />
            <div><small>当前轮次</small><strong>{latest ? `第 ${latest.round_number} 轮` : "尚未训练"}</strong><span>{fresh ? states[current.status] : "STALE_HOLD"}</span></div><ArrowRight size={18} />
            <div><small>人工选定的沙箱模型</small><strong>{short(current.champion_model_id)}</strong><span>{current.champion_model_id === current.initial_model_id ? "仍为初始基线，未证明改善" : "已人工选择，非生产模型"}</span></div>
          </section>
          <section className="learning-members"><h2>数据成员与用途</h2><p>“有缺陷的产品图片”可以是有效训练数据。这里按后端冻结成员展示用途，不把模型预测错误等同于坏数据。</p>
            <div className="learning-splits">{(["train", "val", "test"] as const).map(split => <span key={split}><b>{current.dataset.samples.filter(item => item.split === split).length}</b> {split === "train" ? "训练成员" : split === "val" ? "验证成员 · 不回灌" : "最终测试成员 · 不回灌"}</span>)}</div>
            <details><summary>逐样本查看标签、采集组与版本（{current.dataset.samples.length}）</summary><div className="learning-table-wrap"><table><thead><tr><th>样本</th><th>产品 / 缺陷类别</th><th>当前用途</th><th>采集组</th><th>图像版本</th></tr></thead><tbody>{current.dataset.samples.map(item => <tr key={item.sample_id}>
              <td><Link to={`/workspace?purpose=annotation-rework&asset=${encodeURIComponent(item.sample_id)}`}>{item.sample_id}</Link></td><td>{item.category}{item.mask_origin && <small>具名确认的全零掩膜副本</small>}</td><td>{item.split}</td><td>{item.group_id}</td><td title={item.image_sha256}>{short(item.image_sha256)}</td></tr>)}</tbody></table></div><p>工作簿打开的是当前工作副本；这里保留的是本轮冻结版本。修改后必须重新具名复核、冻结和检查。</p></details>
          </section>
          {latest && <section className="learning-feedback"><h2>本轮反馈收件箱</h2><p>预测分歧只触发复核候选。具名人员需要将其裁定为标签问题、困难样本候选、分布变化候选或证据不足；模型输出本身不是标签真值。</p>
            {!latest.feedback.length && <p>{latest.status === "COMPLETED" ? "本轮没有验证错误候选；这不等于全部数据合格或模型可以生产放行。" : "本轮尚无可用反馈，请查看运行状态。"}</p>}
            {latest.feedback.map(item => <FeedbackCard key={`${item.feedback_id}:${current.receipt_sha256}`} feedback={item} cycle={current} run={latest} canAct={canAct} scope={scope} execute={execute} />)}
          </section>}
          {latest?.evaluation && <EvaluationSummary evaluation={latest.evaluation} title="本轮验证结果" fresh={fresh} />}
          {current.final_evaluation && <EvaluationSummary evaluation={current.final_evaluation} title="已封存的最终测试" fresh={fresh} />}
          {current.final_candidate_accepted === false && <p className="learning-alert">最终测试未接受候选，服务端保留 / 恢复了基线模型。周期已封存，不会继续用最终测试集挑选模型。</p>}
          {current.status === "HOLD_REQUIRES_NEW_PROTOCOL" && <section className="learning-alert"><h2>本周期暂停：需要新的评估协议</h2><p>冻结验证集存在标注问题或证据不足，继续在同一协议中训练与挑选模型会污染比较。请先修订、独立复核并建立新任务与新周期；旧周期和反馈继续保留。</p><Link to="/workspace?purpose=annotation-rework">回工作簿处理</Link></section>}
          {(["READY", "AWAITING_DATA"] as string[]).includes(current.status) && <LearningInput key={current.receipt_sha256} scope={scope} initialTask={current.status === "READY" ? current.dataset.binding.task_id : ""} cycle={current} previousRun={latest} canAct={canAct} execute={execute} />}
          <CycleActions key={current.receipt_sha256} cycle={current} run={latest} scope={scope} canAct={canAct} execute={execute} />
          <details className="learning-history"><summary>轮次、来源与预算记录（{runs.length}）</summary><p>已预留 {current.epochs_reserved} / {current.request.max_total_epochs} 训练轮次，{current.wall_seconds_reserved} / {current.request.max_total_wall_seconds} 秒；预留不等于已消耗。</p>
            {runs.map(run => <article key={run.run_id}><strong>第 {run.round_number} 轮 · {states[run.status]}</strong><p>来源任务 {run.binding.task_id} · 数据 {run.dataset_id}</p><p>模型 {short(run.initial_model_sha256)} → {run.model_sha256 ? short(run.model_sha256) : "尚无候选"}</p><p>{run.selection ? `人工选择：${run.selection.action}` : "未做模型选择"}</p>{run.feedback_parent_run_id && <p>关联上轮 {run.feedback_parent_run_id} 的 {run.responds_to_feedback_ids.length} 条反馈；关联本身不证明逐项修复。</p>}</article>)}
            <h3>当前周期完整回执</h3><pre>{JSON.stringify(current, null, 2)}</pre>
          </details>
        </>}
      </main>
    </div>
  </div>;
}

function EvaluationSummary({ evaluation, title, fresh }: { evaluation: LearningEvaluation; title: string; fresh: boolean }) {
  return <section className="learning-evaluation"><h2>{title} · {!fresh ? "STALE_HOLD · 旧值不可用于选模" : evaluation.decision === "ELIGIBLE" ? "满足沙箱候选条件" : "保留 HOLD"}</h2><p>同一冻结 {evaluation.split} 集、同一评估规则；以下为本地参考模型实测，不是产线 NG 率。</p><table><thead><tr><th>指标</th><th>基线</th><th>候选</th></tr></thead><tbody>{([['Dice', 'dice'], ['漏检率（像素）', 'false_negative_rate'], ['误检率（像素）', 'false_positive_rate']] as const).map(([label, key]) => <tr key={key}><td>{label}</td><td>{metric(evaluation.aggregate.baseline[key])}</td><td>{metric(evaluation.aggregate.candidate[key])}</td></tr>)}</tbody></table>{evaluation.blockers.length > 0 && <details><summary>查看未通过的规则</summary><ul>{evaluation.blockers.map(code => <li key={code}>{code}</li>)}</ul></details>}</section>;
}

function FeedbackCard({ feedback, cycle, run, scope, canAct, execute }: { feedback: LearningFeedback; cycle: LearningCycle; run: LearningRun; scope: LearningScope; canAct: boolean; execute: Execute }) {
  const [classification, setClassification] = useState<Classification | "">("");
  const [note, setNote] = useState(""), [attested, setAttested] = useState(false);
  const reviewed = feedback.status === "TRIAGED_NOT_AUTO_INGESTED";
  const submit = (event: FormEvent) => { event.preventDefault(); if (!classification || !attested) return;
    void execute("feedback", key => reviewLearningFeedback(scope, cycle.cycle_id, run.run_id, feedback.feedback_id, { request_key: key, expected_cycle_sha256: cycle.receipt_sha256, classification, review_note: note, operator_attests_reviewed: true }), { runId: run.run_id, feedbackId: feedback.feedback_id });
  };
  return <article className="learning-feedback-card"><header><div><strong>{feedback.evidence.sample_id}</strong><p>{feedback.evidence.category} · 验证集 · {reviewed ? "已人工分流，未自动加入训练" : "等待人工判因"}</p></div><Link to={`/workspace?purpose=annotation-rework&asset=${encodeURIComponent(feedback.evidence.sample_id)}`}>打开当前工作副本</Link></header>
    <p>候选 Dice {metric(feedback.evidence.candidate.dice)} · 基线 Dice {metric(feedback.evidence.baseline.dice)}；预测差异不是标注错误的证明。</p>
    <FrozenFeedbackPreview scope={scope} source={run.binding} sampleId={feedback.evidence.sample_id} />
    {reviewed ? <div><strong>{feedback.classification ? classifications[feedback.classification][0] : "分类待核验"}</strong><p>{feedback.review_note}</p><p>{feedback.classification && classifications[feedback.classification][1]}</p>{feedback.followup_task_id ? <Link to={`/command-center?task=${encodeURIComponent(feedback.followup_task_id)}`}>查看关联跟进任务（不代表已整改）</Link> : <p>尚未绑定后续任务；本条仍不能认定为整改闭环。</p>}
        <FeedbackFollowupForm scope={scope} cycle={cycle} run={run} feedback={feedback} canAct={canAct} execute={execute} /></div>
      : <form onSubmit={submit}><fieldset disabled={!canAct || cycle.status !== "AWAITING_REVIEW"}><label>反馈分类<select aria-label={`反馈分类 ${feedback.feedback_id}`} value={classification} onChange={event => { setClassification(event.target.value as Classification | ""); setAttested(false); }} required><option value="">请根据证据选择，不自动预判</option>{Object.entries(classifications).map(([key, value]) => <option key={key} value={key}>{value[0]}</option>)}</select></label>
        {classification && <p className="learning-next-action">下一步：{classifications[classification][1]}</p>}
        <label>复核说明<textarea aria-label={`复核说明 ${feedback.feedback_id}`} value={note} onChange={event => setNote(event.target.value)} required minLength={8} maxLength={2000} /></label>
        <label className="learning-check"><input type="checkbox" aria-label={`确认复核 ${feedback.feedback_id}`} checked={attested} onChange={event => setAttested(event.target.checked)} />我已查看样本及其标注，确认上述分类；不授权验证样本回灌训练。</label><button type="submit" disabled={!classification || !attested || note.trim().length < 8}>保存反馈分流</button></fieldset></form>}
  </article>;
}

function FrozenFeedbackPreview({ scope, source, sampleId }: { scope: LearningScope; source: Pick<LearningRun["binding"], "task_id" | "source_id" | "snapshot_receipt_sha256">; sampleId: string }) {
  const [preview, setPreview] = useState(""), [mask, setMask] = useState(""), [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true), urls = useRef<string[]>([]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; urls.current.forEach(url => URL.revokeObjectURL(url)); }; }, []);
  const open = async () => {
    if (busy) return;
    setBusy(true); setError("");
    urls.current.forEach(url => URL.revokeObjectURL(url)); urls.current = [];
    setPreview(""); setMask("");
    const allocated: string[] = [];
    try {
      const manifest = await getTaskVisualEvidence(source.task_id);
      if (manifest.workspace_id !== scope.workspaceId || manifest.project_id !== scope.projectId || manifest.source_id !== source.source_id
        || manifest.operator_snapshot_receipt_sha256 !== source.snapshot_receipt_sha256) throw new Error("冻结视觉证据与本轮来源不一致，已拒绝显示。");
      const item = manifest.items.find(row => row.sample_id === sampleId);
      if (!item) throw new Error("本轮冻结清单中没有此样本；请核对来源任务。");
      const sourceUrl = await loadTaskVisualEvidencePreview(item); allocated.push(sourceUrl);
      const maskUrl = await loadTaskVisualEvidenceMask(item); if (maskUrl) allocated.push(maskUrl);
      if (!mounted.current) { allocated.forEach(url => URL.revokeObjectURL(url)); return; }
      urls.current.forEach(url => URL.revokeObjectURL(url)); urls.current = allocated;
      setPreview(sourceUrl); setMask(maskUrl ?? "");
    } catch (caught) { allocated.forEach(url => URL.revokeObjectURL(url)); if (mounted.current) setError(message(caught)); }
    finally { if (mounted.current) setBusy(false); }
  };
  return <div className="learning-frozen-preview"><button type="button" disabled={busy} onClick={() => void open()}>{busy ? "正在核验图像…" : "查看本轮冻结图与标注"}</button>
    {error && <p role="alert">{error}</p>}
    {preview && <div><figure><img src={preview} alt={`${sampleId} 本轮冻结原图预览`} /><figcaption>冻结原图预览</figcaption></figure>{mask && <figure><img src={mask} alt={`${sampleId} 本轮冻结标注掩膜`} /><figcaption>冻结标注掩膜（不是模型预测）</figcaption></figure>}</div>}
  </div>;
}

const readinessLabels: Record<string, string> = {
  GATE_ELIGIBLE_NOT_TRAINING_APPROVED: "检查通过 · 尚未授权训练",
  NEEDS_ATTENTION: "需要处理具体问题", MASK_REQUIRED_FOR_REFERENCE_TRAINER: "需要标注 / 正常负样本确认",
  BLOCKED_BY_BATCH: "受批次问题阻断", UNVERIFIED: "证据待核验",
  UNVERIFIED_FINDING_IDENTITY: "问题与样本身份未对齐", UNVERIFIED_TOOL_FAILURE: "检查工具失败 · 不作好坏判断",
};

function ReadinessTable({ value }: { value: LearningReadiness }) {
  const [filter, setFilter] = useState("ALL");
  const rows = value.members.filter(item => filter === "ALL" || (filter === "ATTENTION" ? item.readiness_state === "NEEDS_ATTENTION" : filter === "ELIGIBLE" ? item.readiness_state === "GATE_ELIGIBLE_NOT_TRAINING_APPROVED" : !["NEEDS_ATTENTION", "GATE_ELIGIBLE_NOT_TRAINING_APPROVED"].includes(item.readiness_state)));
  return <section className="learning-readiness"><h3>这批数据，分别需要做什么？</h3><p>{value.projection_status === "VERIFIED" ? "冻结检查事实已核验" : "仍有证据未核验，保留未知状态"}；这是用途准入状态，不是产品良品 / 不良品分类。</p>
    <div className="learning-action-row" aria-label="数据处置筛选">{[["ALL", "全部样本"], ["ELIGIBLE", "检查通过"], ["ATTENTION", "需要处理"], ["OTHER", "待补证 / 批次阻断"]].map(([key, label]) => <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key!)}>{label}</button>)}</div>
    <div className="learning-table-wrap"><table><thead><tr><th>样本</th><th>类别 / 用途</th><th>当前处置依据</th><th>具体问题</th></tr></thead><tbody>{rows.map(item => <tr key={item.sample_id}><td><Link to={`/workspace?purpose=annotation-rework&asset=${encodeURIComponent(item.sample_id)}`}>{item.sample_id}</Link></td><td>{item.category} · {item.split}</td><td>{readinessLabels[item.readiness_state] ?? item.readiness_state}</td><td>{item.finding_refs.map(ref => ref.code).join("、") || "无样本级问题记录；不代表批次可放行"}</td></tr>)}</tbody></table></div>
    {!rows.length && <p>当前筛选没有样本。不会把缺失清单显示成全部通过。</p>}
    {value.global_findings.length > 0 && <p className="learning-alert">批次级问题：{value.global_findings.map(item => item.code).join("、")}。不能把它们计作某几张坏图片，也不能忽略后直接训练。</p>}
    {value.unmapped_finding_refs.length > 0 && <p className="learning-alert">有问题尚未绑定到可核验样本，继续保留 HOLD。</p>}
  </section>;
}

function FeedbackFollowupForm({ scope, cycle, run, feedback, canAct, execute }: { scope: LearningScope; cycle: LearningCycle; run: LearningRun; feedback: LearningFeedback; canAct: boolean; execute: Execute }) {
  const [tasks, setTasks] = useState<AgentTask[]>([]), [taskId, setTaskId] = useState("");
  const [projection, setProjection] = useState<LearningReadiness | null>(null), [preflight, setPreflight] = useState<ComputePreflight | null>(null);
  const [selected, setSelected] = useState<string[]>([]), [note, setNote] = useState(""), [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const inspect = async () => {
    setBusy(true); setProjection(null); setPreflight(null); setSelected([]); setAttested(false); setError("");
    try {
      const [gate, readiness] = await Promise.all([getComputePreflight({ ...scope, taskId }), getLearningReadiness(scope, taskId)]);
      if (gate.eligibility !== "READY_FOR_OFFLINE_HANDOFF" || readiness.projection_status !== "VERIFIED" || gate.receipt_sha256 !== readiness.preflight_receipt_sha256 || gate.binding?.source_id === run.binding.source_id) throw new Error("需要同项目中另一版已通过检查的冻结输入；旧任务或未完成的任务不能作跟进证据。");
      if (mounted.current) { setProjection(readiness); setPreflight(gate); }
    } catch (caught) { if (mounted.current) setError(message(caught)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const loadTasks = async () => { try { const rows = await listAgentTasks(scope.workspaceId, scope.projectId); if (mounted.current) setTasks(rows); } catch (caught) { if (mounted.current) setError(message(caught)); } };
  return <details className="learning-followup" onToggle={event => { if (event.currentTarget.open && !tasks.length) void loadTasks(); }}><summary>{feedback.followup ? "已关联新版本证据 · 查看或补充" : "关联返修 / 补采后的新版本证据"}</summary>
    {feedback.followup && <p>已绑定 {feedback.followup.sample_ids.length} 个样本与新 Gate；尚未证明模型错误已修复，不自动关闭问题。</p>}
    <p>先在工作簿返修或补采，重新复核、冻结并运行检查。然后选择那个新任务和真正回应本条反馈的样本。</p>
    <form onSubmit={event => { event.preventDefault(); if (!preflight || !attested || !selected.length) return; void execute("followup", key => linkLearningFeedback(scope, cycle.cycle_id, run.run_id, feedback.feedback_id, { request_key: key, expected_cycle_sha256: cycle.receipt_sha256, expected_run_sha256: run.receipt_sha256, task_id: taskId, expected_preflight_sha256: preflight.receipt_sha256, sample_ids: selected, review_note: note, operator_attests_reviewed: true }), { feedbackId: feedback.feedback_id, runId: run.run_id }); }}>
      <fieldset disabled={!canAct || busy || ["RUNNING", "FINALIZING"].includes(cycle.status)}><label>新版本任务<select value={taskId} onChange={event => { setTaskId(event.target.value); setProjection(null); setPreflight(null); setSelected([]); }} required><option value="">选择已独立检查的新任务</option>{tasks.map(item => <option key={item.task_id} value={item.task_id}>{item.goal} · {item.execution_status}</option>)}</select></label><button type="button" disabled={!taskId} onClick={() => void inspect()}>核验跟进样本</button>
        {error && <p role="alert" className="learning-alert">{error}</p>}
        {projection && <>{projection.members.map(item => <label className="learning-check" key={item.sample_id}><input type="checkbox" checked={selected.includes(item.sample_id)} onChange={event => setSelected(current => event.target.checked ? [...current, item.sample_id] : current.filter(id => id !== item.sample_id))} />{item.sample_id} · {item.category} · {item.split}</label>)}
          <label>这些样本如何回应原反馈<textarea value={note} onChange={event => setNote(event.target.value)} minLength={8} maxLength={2000} required /></label><label className="learning-check"><input type="checkbox" checked={attested} onChange={event => setAttested(event.target.checked)} />我已核对跟进样本及新版本证据；关联不等于问题已经解决。</label><button type="submit" disabled={!attested || !selected.length || note.trim().length < 8}>保存新版本证据关联</button></>}
      </fieldset></form></details>;
}

function LearningInput({ scope, initialTask, cycle, previousRun, canAct, execute }: { scope: LearningScope; initialTask: string; cycle?: LearningCycle; previousRun?: LearningRun; canAct: boolean; execute: Execute }) {
  const [taskId, setTaskId] = useState(initialTask), [tasks, setTasks] = useState<AgentTask[]>([]);
  const [preflight, setPreflight] = useState<ComputePreflight | null>(null), [visual, setVisual] = useState<TaskVisualEvidenceManifest | null>(null);
  const [readiness, setReadiness] = useState<LearningReadiness | null>(null);
  const [normal, setNormal] = useState<Record<string, { reviewer: string; note: string; checked: boolean }>>({});
  const [feedbackIds, setFeedbackIds] = useState<string[]>([]);
  const [groups, setGroups] = useState<Record<string, string>>({}), [checked, setChecked] = useState(false), [loading, setLoading] = useState(false);
  const [error, setError] = useState(""), [note, setNote] = useState(""), [attested, setAttested] = useState(false);
  const [epochs, setEpochs] = useState(80), [rounds, setRounds] = useState(3);
  const active = useRef(true), generation = useRef(0);
  useEffect(() => { active.current = true; void listAgentTasks(scope.workspaceId, scope.projectId).then(value => { if (active.current) setTasks(value); }).catch(error => { if (active.current) setError(message(error)); }); return () => { active.current = false; generation.current++; }; }, [scope]);
  const inspect = async () => {
    const version = ++generation.current; setLoading(true); setChecked(false); setReadiness(null); setError(""); setAttested(false); setFeedbackIds([]);
    try {
      const [next, projection] = await Promise.all([getComputePreflight({ ...scope, taskId }), getLearningReadiness(scope, taskId)]);
      if (!active.current || version !== generation.current) return;
      setPreflight(next);
      if (projection.preflight_receipt_sha256 !== next.receipt_sha256) throw new Error("数据处置投影与预检版本不一致，请重新核验。");
      setReadiness(projection);
      if (next.eligibility !== "READY_FOR_OFFLINE_HANDOFF" || projection.projection_status !== "VERIFIED") { setVisual(null); return; }
      const source = await getTaskVisualEvidence(taskId);
      if (source.task_id !== taskId || source.visual_count !== source.items.length || source.workspace_id !== scope.workspaceId || source.project_id !== scope.projectId || source.source_id !== next.binding?.source_id
        || source.operator_snapshot_receipt_sha256 !== next.binding?.snapshot_receipt_sha256 || source.items.length !== next.binding?.sample_count
        || new Set(source.items.map(item => item.sample_id)).size !== source.items.length) throw new Error("样本清单与预检版本不一致，请重新冻结并检查。");
      if (!active.current || version !== generation.current) return;
      setVisual(source); setGroups(Object.fromEntries(source.items.map(item => [item.sample_id, cycle?.dataset.samples.find(old => old.sample_id === item.sample_id && old.image_sha256 === item.source_sha256)?.group_id ?? ""]))); setChecked(true);
      if (previousRun && ["FAILED", "CANCELLED", "INTERRUPTED"].includes(previousRun.status) && next.receipt_sha256 === previousRun.approval.expected_preflight_sha256) setFeedbackIds([...(previousRun.approval.responds_to_feedback_ids ?? [])]);
      setNormal(Object.fromEntries(source.items.filter(item => !item.mask_sha256).map(item => {
        const previous = cycle?.dataset.normal_mask_attestations?.[item.sample_id];
        const same = previous?.expected_asset_sha256 === item.source_sha256 && previous?.expected_annotation_revision === item.annotation_revision && previous?.expected_annotation_sha256 === item.annotation_document_sha256;
        return [item.sample_id, { reviewer: same ? previous.reviewer_name : "", note: same ? previous.review_note : "", checked: Boolean(same) }];
      })));
    } catch (caught) { if (active.current && version === generation.current) setError(message(caught)); }
    finally { if (active.current && version === generation.current) setLoading(false); }
  };
  const limitations = visual?.items.some(item => item.width > 256 || item.height > 256 || (!item.mask_sha256 && item.annotation_count > 0)) || (visual?.items.length ?? 0) > 64;
  const missingNormalReview = visual?.items.some(item => !item.mask_sha256 && (!normal[item.sample_id]?.checked || (normal[item.sample_id]?.reviewer.trim().length ?? 0) < 2 || (normal[item.sample_id]?.note.trim().length ?? 0) < 8));
  const submit = (event: FormEvent) => { event.preventDefault(); if (!preflight || !checked || !attested || limitations) return;
    if (missingNormalReview || !visual) return;
    const normal_mask_attestations: Record<string, NormalMaskAttestation> = Object.fromEntries(visual.items.filter(item => !item.mask_sha256).map(item => [item.sample_id, { reviewer_name: normal[item.sample_id]!.reviewer, review_note: normal[item.sample_id]!.note, expected_asset_sha256: item.source_sha256, expected_annotation_revision: item.annotation_revision, expected_annotation_sha256: item.annotation_document_sha256, operator_attests_no_foreground: true as const }]));
    const dataset = { expected_preflight_sha256: preflight.receipt_sha256, groups, normal_mask_attestations, operator_attests_training_authorized: true as const, review_note: note };
    if (cycle) void execute("round", key => runLearningRound(scope, cycle.cycle_id, { ...dataset, request_key: key, task_id: taskId, expected_cycle_sha256: cycle.receipt_sha256, responds_to_feedback_ids: feedbackIds }), { taskId });
    else void execute("create", key => createLearningCycle(scope, taskId, { ...dataset, request_key: key, training: { epochs, learning_rate: 0.5, l2: 0, max_wall_seconds: 20, seed: 0 }, max_rounds: rounds, max_total_epochs: epochs * rounds, max_total_wall_seconds: rounds * 20 }), { taskId });
  };
  return <section className="learning-input"><h2>{cycle ? "交入下一轮的数据版本" : "从已复核数据建立学习周期"}</h2><p>{cycle ? "下一轮必须使用新的训练数据版本，验证集和最终测试集保持不变。复核通过不代表自动开始训练。" : "先回工作簿导入真实图片并具名复核，完成五类检查，再选择该任务。建立周期只冻结输入，不启动训练。"}</p>
    <form onSubmit={submit}><fieldset disabled={!canAct || loading}><label>来源任务<select value={taskId} onChange={event => { generation.current++; setTaskId(event.target.value); setPreflight(null); setVisual(null); setReadiness(null); setChecked(false); setAttested(false); }}><option value="">选择当前项目的任务</option>{taskId && !tasks.some(item => item.task_id === taskId) && <option value={taskId}>{taskId}</option>}{tasks.map(item => <option key={item.task_id} value={item.task_id}>{item.goal} · {states[item.execution_status] ?? item.execution_status}</option>)}</select></label><button type="button" disabled={!taskId} onClick={() => void inspect()}>{loading ? "正在核验…" : "核验来源与样本"}</button></fieldset>
      {error && <p role="alert" className="learning-alert">{error} · 输入未核验</p>}
      {preflight?.eligibility === "HOLD" && <p className="learning-alert">输入未通过：{preflight.blockers.join("、")}。<Link to="/workspace?purpose=annotation-rework">返回工作簿处理</Link></p>}
      {readiness && <ReadinessTable value={readiness} />}
      {checked && visual && <fieldset disabled={!canAct || loading}><legend>逐样本确认采集组</legend><p>同一个零件、同一段连续采集的关联图片填写相同采集组；不要为了通过检查给每张图随意编一个组。后端会拒绝跨训练 / 验证 / 测试的同组泄漏。</p>
        <div className="learning-table-wrap"><table><thead><tr><th>冻结样本</th><th>尺寸 / 标注</th><th>真实采集组</th></tr></thead><tbody>{visual.items.map(item => <tr key={item.sample_id}><td>{item.original_name}<small>{item.sample_id}</small></td><td>{item.width} × {item.height} · {item.mask_sha256 ? "有掩膜" : "缺少掩膜"}</td><td><input aria-label={`采集组 ${item.sample_id}`} value={groups[item.sample_id] ?? ""} required maxLength={120} onChange={event => setGroups(current => ({ ...current, [item.sample_id]: event.target.value }))} placeholder="例如本次实际采集的零件组编号" /></td></tr>)}</tbody></table></div>
        <p>当前参考模型限制：最多 64 张、每边最多 256 px、总计 100 万像素、每个文件不超过 4 MiB；每张需二值掩膜，train / val / test 均非空。空标注不自动视为正常样本。</p>
        {visual.items.filter(item => !item.mask_sha256 && item.annotation_count === 0).map(item => <fieldset key={item.sample_id} className="learning-normal-consent">
          <legend>{item.original_name} · 正常负样本确认</legend>
          <p>仅在确认整张冻结图像没有目标前景缺陷后，才能生成全零掩膜学习副本。不会给原图加假框或修改原标注。</p>
          <FrozenFeedbackPreview scope={scope} source={{ task_id: taskId, source_id: visual.source_id, snapshot_receipt_sha256: visual.operator_snapshot_receipt_sha256 }} sampleId={item.sample_id} />
          <label>具名复核人<input value={normal[item.sample_id]?.reviewer ?? ""} minLength={2} maxLength={120} onChange={event => setNormal(current => ({ ...current, [item.sample_id]: { reviewer: event.target.value, note: current[item.sample_id]?.note ?? "", checked: false } }))} /></label>
          <label>无前景缺陷的复核依据<textarea value={normal[item.sample_id]?.note ?? ""} minLength={8} maxLength={2000} onChange={event => setNormal(current => ({ ...current, [item.sample_id]: { reviewer: current[item.sample_id]?.reviewer ?? "", note: event.target.value, checked: false } }))} /></label>
          <label className="learning-check"><input type="checkbox" checked={normal[item.sample_id]?.checked ?? false} onChange={event => setNormal(current => ({ ...current, [item.sample_id]: { reviewer: current[item.sample_id]?.reviewer ?? "", note: current[item.sample_id]?.note ?? "", checked: event.target.checked } }))} />我确认此冻结版本无目标前景缺陷，允许生成全零掩膜副本。</label>
        </fieldset>)}
        {limitations && <p role="alert" className="learning-alert">当前输入超出尺寸 / 数量限制或缺少掩膜。请准备单独的受控小规模版本；不能直接用它启动参考模型。</p>}
        {previousRun && <details><summary>本轮明确回应哪些已关联反馈？（不自动全选）</summary><p>仅可选择已关联到当前新任务、且包含训练成员的反馈。未选中就不会声称本轮回应了该问题。</p>{previousRun.feedback.map(item => { const eligible = item.followup?.binding.task_id === taskId && item.followup.members.some(member => member.split === "train"); return <label className="learning-check" key={item.feedback_id}><input type="checkbox" disabled={!eligible} checked={feedbackIds.includes(item.feedback_id)} onChange={event => setFeedbackIds(current => event.target.checked ? [...current, item.feedback_id] : current.filter(id => id !== item.feedback_id))} />{item.evidence.sample_id} · {eligible ? "已绑定本次输入，可明确关联" : "需先关联本次新版本的训练样本"}</label>; })}</details>}
        {previousRun && ["FAILED", "CANCELLED", "INTERRUPTED"].includes(previousRun.status) && feedbackIds.length > 0 && <p>这是同一已核验输入的重试，沿用上次批准的 {feedbackIds.length} 个反馈标识；未创建新的问题关联。</p>}
        {!cycle && <div className="learning-form-grid"><label>每轮训练 epoch<input type="number" min={1} max={500} value={epochs} onChange={event => setEpochs(Number(event.target.value))} required /></label><label>最多轮数<input type="number" min={1} max={3} value={rounds} onChange={event => setRounds(Number(event.target.value))} required /></label></div>}
        <label>数据复核与训练授权说明<textarea value={note} onChange={event => setNote(event.target.value)} minLength={8} maxLength={2000} required /></label><label className="learning-check"><input type="checkbox" checked={attested} onChange={event => setAttested(event.target.checked)} />我确认采集组及标签经过复核，授权本地 CPU 沙箱{cycle ? "执行这一轮训练与验证" : "冻结学习数据；训练需另行启动"}，不授权数据外发或生产发布。</label>
        <button type="submit" disabled={!attested || Boolean(limitations) || Boolean(missingNormalReview) || note.trim().length < 8 || !visual.items.every(item => groups[item.sample_id]?.trim())}>{cycle ? "授权并运行这一轮" : "创建学习周期（不训练）"}</button>
      </fieldset>}
    </form>
  </section>;
}

function CycleActions({ cycle, run, scope, canAct, execute }: { cycle: LearningCycle; run?: LearningRun; scope: LearningScope; canAct: boolean; execute: Execute }) {
  const [note, setNote] = useState(""), [attested, setAttested] = useState(false);
  const readyForSelection = cycle.status === "AWAITING_REVIEW" && run?.status === "COMPLETED" && run.feedback.every(item => item.status !== "PENDING_HUMAN_REVIEW");
  const allowed = readyForSelection || ["AWAITING_DATA", "RUNNING", "FINALIZING", "READY"].includes(cycle.status);
  if (!allowed) return null;
  const base = (key: string) => ({ request_key: key, expected_cycle_sha256: cycle.receipt_sha256, review_note: note, operator_attests_reviewed: true as const });
  const action = (name: "finalize" | "cancel" | "recover") => {
    if (name === "finalize" && !window.confirm("最终测试只能消费一次，之后关闭本周期，不能继续训练或挑选模型。确认封存？")) return;
    void execute(name, key => learningCycleAction(scope, cycle.cycle_id, name, base(key)));
  };
  return <section className="learning-actions"><h2>人工决策</h2><fieldset disabled={!canAct}><label>决策说明<textarea value={note} onChange={event => setNote(event.target.value)} maxLength={2000} aria-label="模型决策说明" /></label><label className="learning-check"><input type="checkbox" checked={attested} onChange={event => setAttested(event.target.checked)} />我已核对当前回执；这里的批准仅用于本地沙箱，不替代现场专业人员决定。</label>
    <div className="learning-action-row">{readyForSelection && run && <>
      <button disabled={!attested || note.trim().length < 8 || run.evaluation?.decision !== "ELIGIBLE"} onClick={() => void execute("selection", key => selectLearningModel(scope, cycle.cycle_id, run.run_id, { ...base(key), expected_run_sha256: run.receipt_sha256, action: "APPROVE_SANDBOX" }), { runId: run.run_id })}>选用候选（仅沙箱）</button>
      <button disabled={!attested || note.trim().length < 8} onClick={() => void execute("selection", key => selectLearningModel(scope, cycle.cycle_id, run.run_id, { ...base(key), expected_run_sha256: run.receipt_sha256, action: "REJECT" }), { runId: run.run_id })}>拒绝候选，保留原模型</button></>}
      {cycle.status === "AWAITING_DATA" && <button disabled={!attested || note.trim().length < 8} onClick={() => action("finalize")}>结束迭代并封存最终测试</button>}
      {["RUNNING", "FINALIZING"].includes(cycle.status) && <button disabled={!attested || note.trim().length < 8} onClick={() => action("recover")}>核对中断并申请恢复</button>}
      {cycle.status !== "FINALIZING" && <button disabled={!attested || note.trim().length < 8} onClick={() => action("cancel")}>请求停止本周期</button>}
    </div></fieldset></section>;
}
