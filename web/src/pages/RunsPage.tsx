import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  FileJson2,
  Inbox,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  Workflow,
  XCircle,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import type {
  AgentIntervention,
  AgentReleaseReadiness,
  AgentTask,
  AgentTaskEvent,
} from "../agentDomain";
import { EmptyState, StatusBadge } from "../components/ui";
import {
  getAgentReleaseReadiness,
  getAgentTask,
  listAgentInterventions,
  listAgentTaskEvents,
  listAgentTasks,
} from "../data/api";
import type { StatusTone } from "../domain";
import { useProduct } from "../ProductContext";

type RunFilter = "ALL" | "ACTIVE" | "FAILED" | "DONE";

type InspectorSelection =
  | { kind: "task" }
  | { kind: "event"; sequence: number }
  | { kind: "intervention"; interventionId: string };

interface RunDetail {
  task: AgentTask;
  events: AgentTaskEvent[];
  interventions: AgentIntervention[];
  releaseReadiness?: AgentReleaseReadiness;
  unavailable: string[];
}

const privatePayloadKey = /^(chain[_-]?of[_-]?thought|reasoning(?:_content)?|model_reasoning|private_reasoning|internal_thoughts?|thoughts?|system_prompt|developer_prompt)$/i;

function formatTime(value: string | null | undefined, includeSeconds = false): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(includeSeconds ? { second: "2-digit" } : {}),
  }).format(parsed);
}

function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 20 ? `${value.slice(0, 11)}…${value.slice(-6)}` : value;
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : "本地 API 请求失败";
}

function statusTone(value: string | null | undefined): StatusTone {
  const status = (value ?? "").toUpperCase();
  if (/FAILED|ERROR|BLOCKED|REJECT|RECAPTURE|HOLD/.test(status)) return "danger";
  if (/COMPLETED|SUCCEEDED|PASS|VERIFIED|READY/.test(status)) return "success";
  if (/PLANNED|PENDING|WAIT|HUMAN|REVIEW/.test(status)) return "warning";
  if (/CANCELLED|ARCHIVED|NOT_APPLICABLE/.test(status)) return "locked";
  return "info";
}

function isActiveTask(task: AgentTask): boolean {
  return ["CREATED", "PLANNED", "RUNNING", "VERIFYING"].includes(task.execution_status);
}

function parsePayload(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function sanitizePayload(value: unknown, depth = 0): unknown {
  if (depth > 6) return "[depth omitted]";
  if (Array.isArray(value)) {
    const visible = value.slice(0, 80).map((item) => sanitizePayload(item, depth + 1));
    if (value.length > 80) visible.push(`[${value.length - 80} more items omitted]`);
    return visible;
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([key]) => !privatePayloadKey.test(key))
        .map(([key, item]) => [key, sanitizePayload(item, depth + 1)]),
    );
  }
  return value;
}

function findScalar(value: unknown, field: string, depth = 0): string | undefined {
  if (depth > 5 || value === null || value === undefined) return undefined;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 80)) {
      const found = findScalar(item, field, depth + 1);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  const direct = record[field];
  if (["string", "number", "boolean"].includes(typeof direct)) return String(direct);
  for (const item of Object.values(record)) {
    const found = findScalar(item, field, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

function eventErrorCode(event: AgentTaskEvent): string | undefined {
  return findScalar(parsePayload(event.payload_json), "error_code");
}

function RunListSkeleton() {
  return (
    <div className="live-runs-skeleton" aria-label="正在读取任务">
      {[0, 1, 2, 3].map((item) => <span key={item} />)}
    </div>
  );
}

function TaskInspector({ detail }: { detail: RunDetail }) {
  const { task, releaseReadiness, interventions } = detail;
  const decision = task.final_decision ?? task.initial_decision;
  return (
    <div className="live-runs-inspector-body">
      <section className="live-runs-inspector-section">
        <header><Activity size={13} /><strong>执行状态</strong></header>
        <dl className="live-runs-kv">
          <div><dt>execution_status</dt><dd><StatusBadge tone={statusTone(task.execution_status)} compact>{task.execution_status}</StatusBadge></dd></div>
          <div><dt>current_phase</dt><dd>{task.current_phase || "—"}</dd></div>
          <div><dt>runtime_status</dt><dd>{task.runtime_status || "—"}</dd></div>
          <div><dt>started</dt><dd>{formatTime(task.started_at, true)}</dd></div>
          <div><dt>completed</dt><dd>{formatTime(task.completed_at, true)}</dd></div>
        </dl>
      </section>

      <section className="live-runs-inspector-section live-runs-inspector-section--decision">
        <header><ShieldCheck size={13} /><strong>业务裁决</strong></header>
        <dl className="live-runs-kv">
          <div><dt>initial_decision</dt><dd>{task.initial_decision || "尚未形成"}</dd></div>
          <div><dt>final_decision</dt><dd>{task.final_decision || "尚未形成"}</dd></div>
        </dl>
        <p>业务裁决与进程状态分开记录；任务完成不等于生产放行。</p>
        {decision ? <StatusBadge tone={statusTone(decision)}>{decision}</StatusBadge> : null}
      </section>

      {task.execution_status === "FAILED" || task.error_code ? (
        <section className="live-runs-failure-card">
          <header><XCircle size={14} /><strong>{task.error_code ?? "TASK_EXECUTION_FAILED"}</strong></header>
          <p>{task.error_message || "服务端记录任务失败，但未提供额外错误说明。"}</p>
        </section>
      ) : null}

      <section className="live-runs-inspector-section">
        <header><Database size={13} /><strong>任务合同</strong></header>
        <dl className="live-runs-kv">
          <div><dt>task_id</dt><dd title={task.task_id}>{task.task_id}</dd></div>
          <div><dt>source_kind</dt><dd>{task.source_kind}</dd></div>
          <div><dt>source_id</dt><dd title={task.source_id ?? undefined}>{shortId(task.source_id)}</dd></div>
          <div><dt>seed</dt><dd>{task.seed}</dd></div>
          <div><dt>approval_required</dt><dd>{String(task.plan_approval_required)}</dd></div>
          <div><dt>request_sha256</dt><dd title={task.request_sha256}>{shortId(task.request_sha256)}</dd></div>
        </dl>
        <div className="live-runs-tool-chips">
          {task.allowed_tools.map((tool) => <span key={tool}>{tool}</span>)}
        </div>
      </section>

      <section className="live-runs-inspector-section">
        <header><UserCheck size={13} /><strong>人工闸门 · {interventions.length}</strong></header>
        {interventions.length ? (
          <div className="live-runs-compact-ledger">
            {interventions.slice().reverse().slice(0, 4).map((item) => (
              <div key={item.intervention_id}>
                <strong>{item.action}</strong>
                <small>{item.actor_user_id} · {formatTime(item.created_at)}</small>
              </div>
            ))}
          </div>
        ) : <p>服务端尚无人工干预记录。</p>}
      </section>

      {releaseReadiness ? (
        <section className="live-runs-inspector-section">
          <header><CheckCircle2 size={13} /><strong>Release readiness</strong></header>
          <StatusBadge tone={statusTone(releaseReadiness.overall_status)}>{releaseReadiness.overall_status}</StatusBadge>
          <dl className="live-runs-kv">
            <div><dt>evidence_integrity</dt><dd>{releaseReadiness.evidence_integrity}</dd></div>
            <div><dt>source_freshness</dt><dd>{releaseReadiness.source_freshness}</dd></div>
            <div><dt>production_release</dt><dd>false</dd></div>
          </dl>
          <p>{releaseReadiness.required_human_action}</p>
        </section>
      ) : null}
    </div>
  );
}

function EventInspector({ event }: { event: AgentTaskEvent }) {
  const parsedPayload = parsePayload(event.payload_json);
  const safePayload = sanitizePayload(parsedPayload);
  const errorCode = eventErrorCode(event);
  const retryable = findScalar(parsedPayload, "retryable");
  return (
    <div className="live-runs-inspector-body">
      <section className="live-runs-inspector-section">
        <header><FileJson2 size={13} /><strong>持久化事件</strong></header>
        <dl className="live-runs-kv">
          <div><dt>sequence</dt><dd>#{event.sequence}</dd></div>
          <div><dt>status</dt><dd><StatusBadge tone={statusTone(event.status)} compact>{event.status}</StatusBadge></dd></div>
          <div><dt>phase</dt><dd>{event.phase}</dd></div>
          <div><dt>stage</dt><dd>{event.stage}</dd></div>
          <div><dt>recorded_at</dt><dd>{formatTime(event.created_at, true)}</dd></div>
        </dl>
        <p className="live-runs-event-summary">{event.summary}</p>
      </section>

      {errorCode || event.status.toUpperCase().includes("FAIL") ? (
        <section className="live-runs-failure-card">
          <header><AlertTriangle size={14} /><strong>{errorCode ?? "EVENT_FAILED"}</strong></header>
          {retryable !== undefined ? <p>retryable={retryable}</p> : <p>该事件已被服务端标记为失败。</p>}
        </section>
      ) : null}

      <section className="live-runs-inspector-section live-runs-payload">
        <header><Database size={13} /><strong>审计负载</strong></header>
        <p>仅显示服务端事件字段；私有推理与系统提示字段会被过滤。</p>
        <pre>{typeof safePayload === "string" ? safePayload : JSON.stringify(safePayload, null, 2)}</pre>
      </section>
    </div>
  );
}

function InterventionInspector({ intervention }: { intervention: AgentIntervention }) {
  return (
    <div className="live-runs-inspector-body">
      <section className="live-runs-inspector-section">
        <header><UserCheck size={13} /><strong>Append-only intervention</strong></header>
        <dl className="live-runs-kv">
          <div><dt>sequence</dt><dd>#{intervention.sequence}</dd></div>
          <div><dt>action</dt><dd>{intervention.action}</dd></div>
          <div><dt>actor_user_id</dt><dd>{intervention.actor_user_id}</dd></div>
          <div><dt>before_status</dt><dd>{intervention.before_status}</dd></div>
          <div><dt>before_phase</dt><dd>{intervention.before_phase}</dd></div>
          <div><dt>created_at</dt><dd>{formatTime(intervention.created_at, true)}</dd></div>
        </dl>
        <blockquote>{intervention.note || "未填写人工说明"}</blockquote>
        <p>actor_user_id 是本地 API 的操作者标识，不宣称为企业认证身份。</p>
      </section>
      <section className="live-runs-inspector-section">
        <header><ShieldCheck size={13} /><strong>审批绑定</strong></header>
        {intervention.approval_binding ? (
          <dl className="live-runs-kv">
            <div><dt>plan_sha256</dt><dd title={intervention.plan_sha256}>{shortId(intervention.plan_sha256)}</dd></div>
            <div><dt>before_snapshot</dt><dd title={intervention.before_snapshot_sha256}>{shortId(intervention.before_snapshot_sha256)}</dd></div>
            <div><dt>binding_sha256</dt><dd title={intervention.approval_binding.binding_sha256}>{shortId(intervention.approval_binding.binding_sha256)}</dd></div>
            <div><dt>source_profile</dt><dd>{intervention.approval_binding.source_profile_status}</dd></div>
          </dl>
        ) : <p>这条干预没有服务端 approval binding。</p>}
      </section>
    </div>
  );
}

export function RunsPage() {
  const { activeWorkspace, activeProject, connection, workspaceLoading } = useProduct();
  const [searchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [detail, setDetail] = useState<RunDetail>();
  const [selection, setSelection] = useState<InspectorSelection>({ kind: "task" });
  const [filter, setFilter] = useState<RunFilter>("ALL");
  const [query, setQuery] = useState("");
  const [scopeLoading, setScopeLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [scopeError, setScopeError] = useState<string>();
  const [refreshing, setRefreshing] = useState(false);
  const scopeGenerationRef = useRef(0);
  const detailGenerationRef = useRef(0);
  const selectedTaskIdRef = useRef("");
  const scopeKey = `${activeWorkspace?.workspace_id ?? ""}::${activeProject?.project_id ?? ""}`;
  const currentScopeKeyRef = useRef(scopeKey);
  currentScopeKeyRef.current = scopeKey;
  selectedTaskIdRef.current = selectedTaskId;

  const loadScope = useCallback(async (showLoading = true): Promise<string | undefined> => {
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    const requestScopeKey = `${workspaceId ?? ""}::${projectId ?? ""}`;
    const generation = ++scopeGenerationRef.current;
    detailGenerationRef.current += 1;
    setDetailLoading(false);
    if (!workspaceId || !projectId || connection.api !== "CONNECTED") {
      setScopeLoading(false);
      setTasks([]);
      setSelectedTaskId("");
      setDetail(undefined);
      return undefined;
    }
    if (showLoading) setScopeLoading(true);
    setScopeError(undefined);
    try {
      const response = await listAgentTasks(workspaceId, projectId);
      if (generation !== scopeGenerationRef.current || requestScopeKey !== currentScopeKeyRef.current) return undefined;
      const scopedTasks = response
        .filter((task) => task.workspace_id === workspaceId && task.project_id === projectId)
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
      if (scopedTasks.length !== response.length) {
        setScopeError("API 返回了范围外任务；前端已拒绝显示这些记录。");
      }
      setTasks(scopedTasks);
      const stored = window.sessionStorage.getItem(`visiondata:runs-task:${projectId}`) ?? "";
      const current = selectedTaskIdRef.current;
      const requested = scopedTasks.find((task) => task.task_id === requestedTaskId);
      if (requestedTaskId && !requested) {
        setScopeError("深链接 Task 不属于当前 workspace / project，已拒绝定位。");
      }
      const nextId = requestedTaskId
        ? (requested?.task_id ?? "")
        : (
            scopedTasks.find((task) => task.task_id === current)?.task_id ??
            scopedTasks.find((task) => task.task_id === stored)?.task_id ??
            scopedTasks[0]?.task_id ??
            ""
          );
      if (nextId !== current) setDetail(undefined);
      setSelectedTaskId(nextId);
      if (nextId) window.sessionStorage.setItem(`visiondata:runs-task:${projectId}`, nextId);
      if (!nextId) setDetail(undefined);
      return nextId || undefined;
    } catch (caught) {
      if (generation !== scopeGenerationRef.current || requestScopeKey !== currentScopeKeyRef.current) return undefined;
      setTasks([]);
      setSelectedTaskId("");
      setDetail(undefined);
      setScopeError(readableError(caught));
      return undefined;
    } finally {
      if (generation === scopeGenerationRef.current && requestScopeKey === currentScopeKeyRef.current && showLoading) {
        setScopeLoading(false);
      }
    }
  }, [activeProject?.project_id, activeWorkspace?.workspace_id, connection.api, requestedTaskId]);

  const loadDetail = useCallback(async (taskId: string, showLoading = true): Promise<void> => {
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    if (!workspaceId || !projectId || !taskId || connection.api !== "CONNECTED") return;
    const requestScopeKey = `${workspaceId}::${projectId}`;
    const scopeGeneration = scopeGenerationRef.current;
    const detailGeneration = ++detailGenerationRef.current;
    if (showLoading) setDetailLoading(true);
    setScopeError(undefined);
    try {
      const task = await getAgentTask(taskId);
      if (
        requestScopeKey !== currentScopeKeyRef.current ||
        scopeGeneration !== scopeGenerationRef.current ||
        detailGeneration !== detailGenerationRef.current
      ) return;
      if (task.workspace_id !== workspaceId || task.project_id !== projectId || task.task_id !== taskId) {
        setDetail(undefined);
        setScopeError("任务响应与当前 workspace / project 绑定不一致，已拒绝显示。");
        return;
      }
      const requests: [Promise<AgentTaskEvent[]>, Promise<AgentIntervention[]>] = [
        listAgentTaskEvents(taskId),
        listAgentInterventions(taskId),
      ];
      const [eventsResult, interventionsResult] = await Promise.allSettled(requests);
      let readinessResult: PromiseSettledResult<AgentReleaseReadiness> | undefined;
      if (task.execution_status === "COMPLETED") {
        readinessResult = await Promise.allSettled([getAgentReleaseReadiness(taskId)]).then((items) => items[0]);
      }
      if (
        requestScopeKey !== currentScopeKeyRef.current ||
        scopeGeneration !== scopeGenerationRef.current ||
        detailGeneration !== detailGenerationRef.current
      ) return;
      const unavailable: string[] = [];
      const events = eventsResult.status === "fulfilled"
        ? eventsResult.value.slice().sort((left, right) => left.sequence - right.sequence)
        : (unavailable.push(`Events: ${readableError(eventsResult.reason)}`), []);
      const interventions = interventionsResult.status === "fulfilled"
        ? interventionsResult.value.slice().sort((left, right) => left.sequence - right.sequence)
        : (unavailable.push(`Interventions: ${readableError(interventionsResult.reason)}`), []);
      let releaseReadiness: AgentReleaseReadiness | undefined;
      if (readinessResult?.status === "fulfilled") releaseReadiness = readinessResult.value;
      if (readinessResult?.status === "rejected") unavailable.push(`Release readiness: ${readableError(readinessResult.reason)}`);
      setDetail({ task, events, interventions, releaseReadiness, unavailable });
      setTasks((current) => current.map((item) => item.task_id === task.task_id ? task : item));
    } catch (caught) {
      if (
        requestScopeKey === currentScopeKeyRef.current &&
        scopeGeneration === scopeGenerationRef.current &&
        detailGeneration === detailGenerationRef.current
      ) {
        setDetail(undefined);
        setScopeError(readableError(caught));
      }
    } finally {
      if (
        requestScopeKey === currentScopeKeyRef.current &&
        scopeGeneration === scopeGenerationRef.current &&
        detailGeneration === detailGenerationRef.current &&
        showLoading
      ) setDetailLoading(false);
    }
  }, [activeProject?.project_id, activeWorkspace?.workspace_id, connection.api]);

  useEffect(() => {
    setDetail(undefined);
    setSelectedTaskId("");
    setSelection({ kind: "task" });
    void loadScope();
  }, [loadScope]);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(undefined);
      return;
    }
    if (activeProject) {
      window.sessionStorage.setItem(`visiondata:runs-task:${activeProject.project_id}`, selectedTaskId);
    }
    setSelection({ kind: "task" });
    void loadDetail(selectedTaskId);
  }, [activeProject?.project_id, loadDetail, selectedTaskId]);

  useEffect(() => {
    if (!detail || !isActiveTask(detail.task)) return;
    const interval = window.setInterval(() => void loadDetail(detail.task.task_id, false), 2_500);
    return () => window.clearInterval(interval);
  }, [detail?.task.execution_status, detail?.task.task_id, loadDetail]);

  const visibleTasks = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return tasks.filter((task) => {
      if (filter === "ACTIVE" && !isActiveTask(task)) return false;
      if (filter === "FAILED" && task.execution_status !== "FAILED") return false;
      if (filter === "DONE" && !["COMPLETED", "CANCELLED", "ARCHIVED"].includes(task.execution_status)) return false;
      if (!normalizedQuery) return true;
      return [task.task_id, task.goal, task.execution_status, task.current_phase, task.final_decision, task.error_code]
        .some((value) => value?.toLocaleLowerCase().includes(normalizedQuery));
    });
  }, [filter, query, tasks]);

  useEffect(() => {
    if (
      requestedTaskId ||
      visibleTasks.some((task) => task.task_id === selectedTaskId)
    ) return;
    setDetail(undefined);
    setSelection({ kind: "task" });
    setSelectedTaskId(visibleTasks[0]?.task_id ?? "");
  }, [requestedTaskId, selectedTaskId, visibleTasks]);

  const selectedEvent = selection.kind === "event"
    ? detail?.events.find((event) => event.sequence === selection.sequence)
    : undefined;
  const selectedIntervention = selection.kind === "intervention"
    ? detail?.interventions.find((item) => item.intervention_id === selection.interventionId)
    : undefined;

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    const before = selectedTaskIdRef.current;
    const next = await loadScope(false);
    if (next && next === before) await loadDetail(next, false);
    setRefreshing(false);
  };

  if (workspaceLoading) {
    return <div className="live-runs-page live-runs-page--center"><LoaderCircle className="is-spinning" size={18} /> 正在读取工作范围…</div>;
  }

  if (!activeWorkspace || !activeProject) {
    return (
      <div className="live-runs-page live-runs-page--center">
        <EmptyState icon={Inbox} title="尚未选择真实项目" description="先在左侧创建或选择项目，再进入运行工作台。" />
      </div>
    );
  }

  return (
    <div className="live-runs-page">
      <header className="live-runs-toolbar">
        <div>
          <Workflow size={15} />
          <strong>运行工作台</strong>
          <span>{activeWorkspace.name} / {activeProject.name}</span>
        </div>
        <div className="live-runs-toolbar__facts">
          <span><i className="is-active" />活动 {tasks.filter(isActiveTask).length}</span>
          <span><i className="is-failed" />失败 {tasks.filter((task) => task.execution_status === "FAILED").length}</span>
          <span><i className="is-done" />完成 {tasks.filter((task) => task.execution_status === "COMPLETED").length}</span>
          <button type="button" onClick={() => void refresh()} disabled={refreshing || connection.api !== "CONNECTED"} title="刷新服务端任务与事件">
            <RefreshCw className={refreshing ? "is-spinning" : ""} size={13} /> 刷新
          </button>
        </div>
      </header>

      {scopeError ? <div className="live-runs-notice"><AlertTriangle size={13} /><span>{scopeError}</span></div> : null}
      {connection.api !== "CONNECTED" ? (
        <div className="live-runs-notice"><AlertTriangle size={13} /><span>本地 API 未连接；本页不回退到 fixture，也不会填充演示运行。</span></div>
      ) : null}

      <div className="live-runs-grid">
        <aside className="live-runs-tasks">
          <header>
            <span><Inbox size={13} /> TASKS</span>
            <b>{tasks.length}</b>
          </header>
          <label className="live-runs-search">
            <Search size={12} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、状态或错误码" />
          </label>
          <nav className="live-runs-filters" aria-label="运行筛选">
            {(["ALL", "ACTIVE", "FAILED", "DONE"] as const).map((item) => (
              <button key={item} type="button" className={filter === item ? "is-active" : ""} onClick={() => setFilter(item)}>{item}</button>
            ))}
          </nav>
          <div className="live-runs-task-list">
            {scopeLoading ? <RunListSkeleton /> : null}
            {!scopeLoading && connection.api === "CONNECTED" && tasks.length === 0 ? (
              <div className="live-runs-empty">
                <CircleDot size={18} />
                <strong>当前项目还没有任务</strong>
                <p>这里仅显示服务端任务账本，不自动生成示例数据。</p>
                <Link to="/command-center">前往 Agent 中心创建任务</Link>
              </div>
            ) : null}
            {!scopeLoading && tasks.length > 0 && visibleTasks.length === 0 ? (
              <div className="live-runs-empty"><Search size={17} /><strong>没有匹配任务</strong><p>修改筛选条件或搜索词。</p></div>
            ) : null}
            {!scopeLoading && visibleTasks.map((task) => {
              const decision = task.final_decision ?? task.initial_decision;
              return (
                <button
                  type="button"
                  key={task.task_id}
                  className={selectedTaskId === task.task_id ? "is-selected" : ""}
                  onClick={() => {
                    if (task.task_id !== selectedTaskId) setDetail(undefined);
                    setSelectedTaskId(task.task_id);
                  }}
                >
                  <i className={`is-${statusTone(task.execution_status)}`} />
                  <div>
                    <strong>{task.goal}</strong>
                    <small>{shortId(task.task_id)} · {formatTime(task.updated_at)}</small>
                    <span>
                      <StatusBadge tone={statusTone(task.execution_status)} compact>{task.execution_status}</StatusBadge>
                      {decision ? <em>{decision}</em> : <em>NO DECISION</em>}
                    </span>
                    {task.error_code ? <code>{task.error_code}</code> : null}
                  </div>
                  <ChevronRight size={12} />
                </button>
              );
            })}
          </div>
          <footer>scope · {shortId(activeWorkspace.workspace_id)} / {shortId(activeProject.project_id)}</footer>
        </aside>

        <main className="live-runs-timeline">
          {!selectedTaskId ? (
            <div className="live-runs-canvas-empty"><Activity size={20} /><strong>选择一条真实任务</strong><p>事件时间线来自服务端持久化账本。</p></div>
          ) : detailLoading && !detail ? (
            <div className="live-runs-canvas-empty"><LoaderCircle className="is-spinning" size={18} /><strong>正在读取任务事件…</strong></div>
          ) : detail ? (
            <>
              <header className="live-runs-task-header">
                <div>
                  <span>SERVER TASK · {shortId(detail.task.task_id)}</span>
                  <h1>{detail.task.goal}</h1>
                  <p>更新时间 {formatTime(detail.task.updated_at, true)} · phase {detail.task.current_phase || "—"}</p>
                </div>
                <button type="button" onClick={() => setSelection({ kind: "task" })} className={selection.kind === "task" ? "is-active" : ""}>
                  <FileJson2 size={12} /> 任务合同
                </button>
              </header>

              <section className="live-runs-dual-state">
                <article>
                  <span>执行状态 / PROCESS</span>
                  <strong><StatusBadge tone={statusTone(detail.task.execution_status)}>{detail.task.execution_status}</StatusBadge></strong>
                  <small>{detail.task.current_phase || "尚无阶段"} · {detail.task.runtime_status || "runtime 未记录"}</small>
                </article>
                <article>
                  <span>业务裁决 / DECISION</span>
                  <strong>{detail.task.final_decision ?? detail.task.initial_decision ?? "尚未形成"}</strong>
                  <small>进程完成不自动授予生产放行权</small>
                </article>
              </section>

              {detail.task.execution_status === "FAILED" || detail.task.error_code ? (
                <section className="live-runs-task-failure">
                  <XCircle size={15} />
                  <div><strong>{detail.task.error_code ?? "TASK_EXECUTION_FAILED"}</strong><p>{detail.task.error_message || "服务端未提供额外错误说明。"}</p></div>
                  <span>FAIL-CLOSED</span>
                </section>
              ) : null}

              {detail.unavailable.length ? (
                <section className="live-runs-partial"><AlertTriangle size={13} /><span>部分只读接口不可用：{detail.unavailable.join("；")}</span></section>
              ) : null}

              <section className="live-runs-event-ledger">
                <header>
                  <div><Clock3 size={13} /><strong>服务端事件时间线</strong></div>
                  <span>{detail.events.length} EVENTS · 按 sequence 排序</span>
                </header>
                {detail.events.length ? (
                  <div className="live-runs-events">
                    {detail.events.map((event) => {
                      const errorCode = eventErrorCode(event);
                      const isSelected = selection.kind === "event" && selection.sequence === event.sequence;
                      return (
                        <button
                          type="button"
                          key={`${event.task_id}-${event.sequence}`}
                          className={`${isSelected ? "is-selected " : ""}is-${statusTone(event.status)}`}
                          onClick={() => setSelection({ kind: "event", sequence: event.sequence })}
                        >
                          <span className="live-runs-event-sequence">{String(event.sequence).padStart(2, "0")}</span>
                          <span className="live-runs-event-line" />
                          <div>
                            <header>
                              <strong>{event.phase} / {event.stage}</strong>
                              <StatusBadge tone={statusTone(event.status)} compact>{event.status}</StatusBadge>
                              <time>{formatTime(event.created_at, true)}</time>
                            </header>
                            <p>{event.summary}</p>
                            {errorCode ? <code><XCircle size={10} /> error_code={errorCode}</code> : null}
                          </div>
                          <ChevronRight size={12} />
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="live-runs-ledger-empty"><Clock3 size={17} /><strong>服务端尚未记录 Event</strong><p>页面不会补写阶段或伪造工具回执。</p></div>
                )}
              </section>

              <section className="live-runs-event-ledger live-runs-human-ledger">
                <header>
                  <div><UserCheck size={13} /><strong>人工闸门账本</strong></div>
                  <span>{detail.interventions.length} INTERVENTIONS</span>
                </header>
                {detail.interventions.length ? (
                  <div>
                    {detail.interventions.map((item) => (
                      <button
                        type="button"
                        key={item.intervention_id}
                        className={selection.kind === "intervention" && selection.interventionId === item.intervention_id ? "is-selected" : ""}
                        onClick={() => setSelection({ kind: "intervention", interventionId: item.intervention_id })}
                      >
                        <span>#{item.sequence}</span>
                        <div><strong>{item.action}</strong><small>{item.actor_user_id} · {formatTime(item.created_at, true)}</small></div>
                        <ChevronRight size={12} />
                      </button>
                    ))}
                  </div>
                ) : <div className="live-runs-ledger-empty"><UserCheck size={16} /><strong>尚无人工干预</strong></div>}
              </section>
            </>
          ) : (
            <div className="live-runs-canvas-empty"><AlertTriangle size={18} /><strong>任务详情不可用</strong><p>保留左侧任务选择，可再次刷新服务端。</p></div>
          )}
        </main>

        <aside className="live-runs-inspector">
          <header>
            <div>
              {selection.kind === "event" ? <FileJson2 size={13} /> : selection.kind === "intervention" ? <UserCheck size={13} /> : <ShieldCheck size={13} />}
              <span>{selection.kind === "event" ? "EVENT INSPECTOR" : selection.kind === "intervention" ? "HUMAN GATE" : "TASK INSPECTOR"}</span>
            </div>
            {detail ? <button type="button" onClick={() => setSelection({ kind: "task" })}>TASK</button> : null}
          </header>
          {detailLoading && !detail ? (
            <div className="live-runs-inspector-empty"><LoaderCircle className="is-spinning" size={17} />正在读取</div>
          ) : !detail ? (
            <div className="live-runs-inspector-empty"><FileJson2 size={17} />选择任务后检查证据</div>
          ) : selectedEvent ? (
            <EventInspector event={selectedEvent} />
          ) : selectedIntervention ? (
            <InterventionInspector intervention={selectedIntervention} />
          ) : (
            <TaskInspector detail={detail} />
          )}
          <footer><ShieldCheck size={11} /> persisted records · no private chain-of-thought</footer>
        </aside>
      </div>
    </div>
  );
}
