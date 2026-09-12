import { Activity, ArrowRight, Layers3, RefreshCw, Search, Settings2, ShieldCheck, Wrench } from "lucide-react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useProduct } from "../ProductContext";
import { ActionButton, Metric, Panel, PanelHeader, StatusBadge } from "../components/ui";
import { getAgentPlatform, getTaskExecutionRecovery, getTaskModelUsage, recoverTaskExecution, type AgentPlatformOverview,
  type AgentPlatformScope, type TaskExecutionRecoveryProjection, type TaskExecutionRecoveryReceipt, type TaskModelUsageReport } from "../data/agentPlatformApi";
import { OperatorApiError } from "../data/api";
import "../styles/agent-platform.css";
import { PlatformWorkflow } from "../components/PlatformWorkflow";
import { getIdentitySessionSnapshot, subscribeIdentitySession } from "../identitySession";
import "../styles/start-surfaces.css";

function describeError(error: unknown): string {
  return error instanceof OperatorApiError ? `${error.code} · ${error.message}` : "读取未完成，请检查本地 API 后重试。";
}

const recoveryDescriptions: Record<TaskExecutionRecoveryProjection["classification"], string> = {
  OWNED_RUNNING: "当前任务仍有执行者，继续查看运行记录。",
  INTERRUPTED: "执行已中断。可具名创建替代任务，并重新审批执行计划。",
  LEGACY_UNKNOWN: "历史任务的执行归属无法确认，需要人工调查。",
  NOT_APPLICABLE: "当前任务不需要中断恢复。",
};

function TaskRuntimeDetail({ scope, taskId }: { scope: AgentPlatformScope; taskId: string }) {
  const [usage, setUsage] = useState<TaskModelUsageReport>();
  const [usageError, setUsageError] = useState<string>();
  const [recovery, setRecovery] = useState<TaskExecutionRecoveryProjection>();
  const [recoveryError, setRecoveryError] = useState<string>();
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [attested, setAttested] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState<string>();
  const [receipt, setReceipt] = useState<TaskExecutionRecoveryReceipt>();
  const active = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setRecovery(undefined);
    setRecoveryError(undefined);
    setUsage(undefined);
    setUsageError(undefined);
    setMutationError(undefined);
    setAttested(false);
    void Promise.allSettled([getTaskExecutionRecovery(scope, taskId), getTaskModelUsage(scope, taskId)]).then(([recoveryResult, usageResult]) => {
      if (!current) return;
      if (recoveryResult.status === "fulfilled") setRecovery(recoveryResult.value);
      else setRecoveryError(describeError(recoveryResult.reason));
      if (usageResult.status === "fulfilled") setUsage(usageResult.value);
      else setUsageError(describeError(usageResult.reason));
      setLoading(false);
    });
    return () => { current = false; };
  }, [scope.workspaceId, scope.projectId, taskId, refreshVersion]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (inFlight.current || !recovery?.can_recover || recovery.classification !== "INTERRUPTED"
      || receipt || mutationError || !attested || reviewer.trim().length < 2 || note.trim().length < 2) return;
    inFlight.current = true;
    setMutating(true);
    try {
      const value = await recoverTaskExecution(scope, taskId, {
        expectedSnapshotSha256: recovery.task_snapshot_sha256, reviewerIdentity: reviewer.trim(), note: note.trim(), operatorAttestsRecovery: true,
      });
      if (active.current) { setReceipt(value); setAttested(false); }
    } catch (caught) {
      if (active.current) setMutationError(describeError(caught));
    } finally {
      inFlight.current = false;
      if (active.current) setMutating(false);
    }
  };

  return (
    <>
    <section className="agent-platform-usage" aria-label="所选任务模型用量">
      <header><strong>模型调用与用量</strong><StatusBadge tone="info" compact>已保存运行证据</StatusBadge></header>
      {loading ? <p role="status">正在读取模型用量回执…</p> : null}
      {usageError ? <p role="alert">用量 UNKNOWN · {usageError}</p> : null}
      {usage ? <>
        <p><StatusBadge tone={usage.summary.call_status === "UNKNOWN" ? "warning" : "info"}>{usage.summary.call_status}</StatusBadge>
          <span> · {usage.summary.usage_completeness}</span></p>
        <div className="agent-platform-metrics">
          <Metric label="远端逻辑调用" value={usage.summary.logical_model_calls === null ? "未知" : String(usage.summary.logical_model_calls)} detail="已保存任务与 Incident Planner" />
          <Metric label="远端传输尝试" value={usage.summary.transport_attempts === null ? "未知" : String(usage.summary.transport_attempts)} detail="包含重试" />
          <Metric label="供应商报告 Token" value={usage.summary.total_tokens === null ? "未知" : String(usage.summary.total_tokens)} detail={`输入 ${usage.summary.input_tokens ?? "未知"} / 输出 ${usage.summary.output_tokens ?? "未知"}`} />
          <Metric label="费用" value="未配置计价" detail="NOT_CONFIGURED · 不等同于免费或零费用" />
        </div>
        <p>统计当前任务中已保存的远端调用；本地模型调用 {usage.summary.local_model_calls ?? "未知"}，回放回执 {usage.summary.replay_receipt_count}，均不计入远端 Token。</p>
        {usage.summary.unreported_attempt_count > 0 ? <p>有 {usage.summary.unreported_attempt_count} 次传输尝试缺少用量，汇总 Token 保持未知。</p> : null}
        {usage.unavailable_reasons.length > 0 ? <small>缺失依据：{usage.unavailable_reasons.join(" · ")}</small> : null}
        <details><summary>查看 {usage.records.length} 条用量来源</summary>
          <div className="agent-platform-usage-records">{usage.records.map((item, index) => <article key={`${item.source_kind}:${item.case_id ?? "core"}:${index}`}>
            <strong>{item.source_kind} · {item.origin} · {item.outcome}</strong>
            <p>最后响应 Token：{item.total_tokens ?? "未知"} · {item.usage_completeness} · {item.token_scope}</p>
            {item.estimated_input_tokens !== null ? <small>预估输入 {item.estimated_input_tokens} Token，仅为估算，未计入实际用量。</small> : null}
            <code title={item.source_receipt_sha256 ?? undefined}>来源 SHA {item.source_receipt_sha256?.slice(0, 16) ?? "未知"}</code>
          </article>)}</div>
        </details>
        <small title={usage.receipt_sha256}>用量回执已核验 · {usage.receipt_sha256.slice(0, 16)}…</small>
      </> : null}
    </section>
    <section className="agent-platform-recovery" aria-label="所选任务运行详情">
      <header><strong>执行恢复</strong><ActionButton variant="secondary" icon={RefreshCw} disabled={loading || mutating}
        onClick={() => setRefreshVersion((current) => current + 1)}>重新核验任务</ActionButton></header>
      {loading ? <p role="status">正在核验任务执行归属…</p> : null}
      {recoveryError ? <p role="alert">执行恢复状态 UNKNOWN · {recoveryError}</p> : null}
      {recovery ? (
        <>
          <p><StatusBadge tone={recovery.can_recover ? "warning" : "info"}>{recovery.classification}</StatusBadge></p>
          <p>{receipt ? "恢复前执行状态" : "当前执行状态"}：{recovery.execution_status}</p>
          <p>{receipt ? "已签发替代任务，后续执行需要在新任务中重新审批。" : recoveryDescriptions[recovery.classification]}</p>
          <small>依据：{recovery.reason_codes.join(" · ") || "未列出附加原因"}</small>
          <code title={recovery.task_snapshot_sha256}>任务快照 {recovery.task_snapshot_sha256.slice(0, 16)}…</code>
          {recovery.can_recover && !receipt ? (
            <form className="agent-platform-recovery-form" onSubmit={(event) => void submit(event)}>
              <label>复核人姓名 / 工号<input aria-label="恢复复核人" value={reviewer} onChange={(event) => setReviewer(event.target.value)} minLength={2} maxLength={120} required disabled={mutating} /></label>
              <label>恢复依据<textarea aria-label="恢复依据" value={note} onChange={(event) => setNote(event.target.value)} minLength={2} maxLength={1000} rows={3} required disabled={mutating} /></label>
              <label className="agent-platform-attestation"><input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} disabled={mutating} />我已复核中断证据，确认创建替代任务；执行计划仍需重新审批。</label>
              <ActionButton type="submit" disabled={loading || mutating || Boolean(mutationError) || !attested || reviewer.trim().length < 2 || note.trim().length < 2}>
                {mutating ? "正在提交恢复请求…" : "具名创建替代任务"}
              </ActionButton>
            </form>
          ) : null}
        </>
      ) : null}
      {mutationError ? <p role="alert">恢复结果尚未核实，已停止重复提交。请重新核验任务后再操作。{mutationError}</p> : null}
      {receipt ? <div role="status"><strong>替代任务已创建，等待新计划审批。</strong>
        <p><Link to={`/command-center?task=${encodeURIComponent(receipt.replacement_task_id)}`}>打开替代任务并人工审批 <ArrowRight size={14} /></Link></p>
        <small>未自动启动 · 回执 {receipt.receipt_sha256.slice(0, 16)}…</small></div> : null}
    </section>
    </>
  );
}

export function AgentPlatformPage() {
  const { activeWorkspace, activeProject, connection } = useProduct();
  const identity = useSyncExternalStore(subscribeIdentitySession, getIdentitySessionSnapshot, getIdentitySessionSnapshot);
  const [taskQuery, setTaskQuery] = useState("");
  const [taskFilter, setTaskFilter] = useState("all");
  const [searchParams, setSearchParams] = useSearchParams();
  const workspaceId = activeWorkspace?.workspace_id;
  const projectId = activeProject?.project_id;
  const scopeKey = `${identity.generation}::${workspaceId ?? ""}::${projectId ?? ""}::${connection?.api ?? "CONNECTED"}`;
  const apiUnavailable = connection !== undefined && connection.api !== "CONNECTED";
  const scopeIdentity = useRef({ key: scopeKey, generation: 0 });
  if (scopeIdentity.current.key !== scopeKey) {
    scopeIdentity.current = { key: scopeKey, generation: scopeIdentity.current.generation + 1 };
  }
  const requestVersion = useRef(0);
  const [overview, setOverview] = useState<{ scope: string; value: AgentPlatformOverview }>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const platform = overview?.scope === scopeKey ? overview.value : undefined;
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const selectedTask = platform?.tasks.find((task) => task.task_id === requestedTaskId);
  const filteredTasks = platform?.tasks.filter((task) => {
    const matchesText = `${task.goal} ${task.task_id} ${task.execution_status}`.toLocaleLowerCase().includes(taskQuery.trim().toLocaleLowerCase());
    const matchesState = taskFilter === "all" || (taskFilter === "active" ? ["CREATED", "PLANNED", "RUNNING", "VERIFYING"].includes(task.execution_status) : task.execution_status === "FAILED");
    return matchesText && matchesState;
  }) ?? [];

  const refresh = useCallback(async () => {
    const request = ++requestVersion.current;
    const generation = scopeIdentity.current.generation;
    const current = () => request === requestVersion.current && scopeKey === scopeIdentity.current.key
      && generation === scopeIdentity.current.generation;
    setOverview(undefined);
    setError(undefined);
    if (!workspaceId || !projectId || apiUnavailable) { setLoading(false); return; }
    setLoading(true);
    try {
      const value = await getAgentPlatform({ workspaceId, projectId });
      if (current()) setOverview({ scope: scopeKey, value });
    } catch (caught) {
      if (current()) setError(describeError(caught));
    } finally {
      if (current()) setLoading(false);
    }
  }, [workspaceId, projectId, scopeKey, apiUnavailable]);

  useEffect(() => {
    void refresh();
    return () => { requestVersion.current += 1; };
  }, [refresh]);

  return (
    <div className="agent-platform-page start-platform">
      <header className="agent-platform-header">
        <div>
          <span className="start-kicker">{activeProject?.name ?? "当前项目"}</span>
          <h1>任务总览</h1>
          <p>查看正在做的工作，复核中断原因，再决定下一步。</p>
        </div>
        <div className="start-platform-actions"><Link to="/models">模型与 API</Link><ActionButton variant="secondary" icon={RefreshCw} disabled={loading || apiUnavailable} onClick={() => void refresh()}>刷新平台状态</ActionButton></div>
      </header>

      <PlatformWorkflow />

      {apiUnavailable ? <p className="start-read-error" role="alert">工作台 API 未连接，当前任务状态未知。请在连接状态中重新检查服务；不会显示上次的成功结果。</p> : null}

      {!workspaceId || !projectId ? (
        <Panel variant="raised">
          <PanelHeader title="请先选择工作空间和项目" detail="平台能力与任务记录按当前项目读取。" />
          <Link to="/workspace">打开图像工作簿 <ArrowRight size={14} /></Link>
        </Panel>
      ) : null}
      {loading ? <p role="status">正在核验当前项目的平台回执…</p> : null}
      {error ? (
        <Panel variant="danger">
          <PanelHeader title="平台状态暂不可确认" detail="未成功读取的配置、任务和用量不会记为零。" />
          <p role="alert">{error}</p>
        </Panel>
      ) : null}

      {platform ? (
        <>
          <div className="agent-platform-metrics start-platform-summary">
            <Metric label="已登记能力" value={String(platform.capabilities.length)} detail="以服务端能力清单为准" icon={Wrench} />
            <Metric label="模型配置" value={`${platform.providers.enabled_count} 启用 / ${platform.providers.configured_count} 已配置`} detail="连接尚未实测 · NOT_PROBED" icon={Settings2} />
            <Metric label="当前项目任务" value={String(platform.task_count)} detail={platform.tasks_truncated ? `列表显示前 ${platform.task_limit} 项 / 共 ${platform.task_count} 项` : "当前项目已返回的执行记录"} icon={Activity} />
          </div>



          <Panel>
            <PanelHeader title="执行记录" detail="选择任务，查看模型用量、执行状态与人工审批入口。" />
            <div className="start-task-controls"><label className="start-search"><Search size={16} /><span className="start-visually-hidden">搜索当前项目任务</span><input type="search" aria-label="搜索当前项目任务" placeholder="按任务目标或编号搜索" value={taskQuery} onChange={(event) => setTaskQuery(event.target.value)} />{taskQuery ? <button type="button" onClick={() => setTaskQuery("")}>清除</button> : null}</label>
              <label>状态<select aria-label="任务状态筛选" value={taskFilter} onChange={(event) => setTaskFilter(event.target.value)}><option value="all">全部任务</option><option value="active">未完成</option><option value="failed">执行失败</option></select></label>
            </div>
            {platform.tasks_truncated ? <p className="start-note">搜索仅覆盖当前返回的 {platform.tasks.length} 项，不代表全部 {platform.task_count} 项。</p> : null}
            {requestedTaskId && !selectedTask ? <p role="alert">指定任务不在当前项目的已验证列表中，已停止读取详情。若列表已截断，请在运行页面定位任务。</p> : null}
            {platform.tasks.length === 0 ? <p>当前项目尚无任务记录。可在图像工作簿封存项目快照后创建任务。</p> : (
              <div className="agent-platform-task-list" aria-label="当前项目任务">
                {filteredTasks.map((task) => (
                  <button type="button" key={task.task_id} className={selectedTask?.task_id === task.task_id ? "is-selected" : ""}
                    aria-pressed={selectedTask?.task_id === task.task_id}
                    onClick={() => setSearchParams((current) => { const next = new URLSearchParams(current); next.set("task", task.task_id); return next; })}>
                    <span><strong>{task.goal}</strong><small>{task.task_id}</small></span>
                    <span><StatusBadge tone="info" compact>{task.execution_status}</StatusBadge><small>门禁：{task.final_decision ?? "尚无裁决"}</small></span>
                  </button>
                ))}
              </div>
            )}
            {platform.tasks.length > 0 && filteredTasks.length === 0 ? <p className="start-note" role="status">没有匹配的任务。请调整关键词或状态筛选；没有修改任务记录。</p> : null}
            {selectedTask ? (
              <div className="agent-platform-task-detail" key={`${scopeKey}::${selectedTask.task_id}`}>
                {!filteredTasks.some((task) => task.task_id === selectedTask.task_id) ? <p className="start-note">所选任务不在当前筛选结果中；下方仍显示你已选择的任务。</p> : null}
                <strong><Layers3 size={16} /> {selectedTask.goal}</strong>
                <Link to={`/command-center?task=${encodeURIComponent(selectedTask.task_id)}`}>打开任务与人工审批 <ArrowRight size={14} /></Link>
                <TaskRuntimeDetail scope={{ workspaceId: platform.workspace_id, projectId: platform.project_id }} taskId={selectedTask.task_id} />
              </div>
            ) : <p>请选择任务以查看运行详情。</p>}
          </Panel>

          <Panel className="start-capability-panel">
            <PanelHeader title="可用工具与运行能力" detail="服务端已登记的能力，不代表本次任务已执行，也不代表工厂在线。" />
            <div className="agent-platform-capabilities">
              {platform.capabilities.map((capability) => (
                <article key={capability.capability_id}>
                  <header><strong>{capability.name}</strong><StatusBadge tone="info" compact>{capability.status}</StatusBadge></header>
                  <p>{capability.description}</p>
                  <small>{capability.kind} · {capability.capability_id}</small>
                </article>
              ))}
              {platform.capabilities.length === 0 ? <p>此回执未列出已登记能力。</p> : null}
            </div>
          </Panel>

          <footer className="agent-platform-receipt">
            <ShieldCheck size={16} /><span>当前项目回执已核验</span>
            <code title={platform.receipt_sha256}>{platform.receipt_sha256.slice(0, 16)}…</code>
            <span>LOCAL_WORKSPACE · 已读取工作台 API，不代表工厂在线连接</span>
          </footer>
        </>
      ) : null}
    </div>
  );
}
