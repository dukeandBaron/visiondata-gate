import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDot,
  Database,
  FileKey2,
  GitBranch,
  Hash,
  Link2,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  Workflow,
  XCircle,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useSearchParams } from "react-router-dom";
import { useProduct } from "../ProductContext";
import type {
  AgentCapaLineageRecord,
  AgentTask,
  AgentTaskLineageEdge,
  AgentTaskLineageNode,
  AgentTaskLineageReport,
  IndustrialIncident,
} from "../agentDomain";
import {
  getAgentTaskLineage,
  listAgentCapaLineageRecords,
  listAgentTasks,
  listIndustrialIncidentV5,
  OperatorApiError,
} from "../data/api";
import type { StatusTone } from "../domain";
import {
  ActionButton,
  ClaimBoundary,
  Digest,
  EmptyState,
  EvidenceSourceBadge,
  StatusBadge,
} from "../components/ui";

interface RelatedRecords {
  incidentsByTask: Record<string, IndustrialIncident[]>;
  capasByTask: Record<string, AgentCapaLineageRecord[]>;
  errorsByTask: Record<string, string[]>;
}

const emptyRelated: RelatedRecords = {
  incidentsByTask: {},
  capasByTask: {},
  errorsByTask: {},
};

function shortDigest(value: string | null | undefined, length = 12): string {
  if (!value) return "未生成";
  return `${value.slice(0, length)}…${value.slice(-5)}`;
}

function readableError(error: unknown): string {
  if (error instanceof OperatorApiError) return `${error.code} · ${error.message}`;
  if (error instanceof Error && error.name === "AbortError") return "本地 API 请求超时";
  if (error instanceof Error) return error.message;
  return "无法读取本地 API";
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function taskTone(status: AgentTask["execution_status"]): StatusTone {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED" || status === "CANCELLED") return "danger";
  if (status === "RUNNING" || status === "VERIFYING") return "info";
  if (status === "PLANNED") return "warning";
  return "neutral";
}

function capaTone(status: AgentCapaLineageRecord["status"]): StatusTone {
  if (status === "RECOVERED_TO_HUMAN_REVIEW" || status === "CHILD_RUN_COMPLETED") {
    return "success";
  }
  if (status === "STILL_BLOCKED" || status === "TRANSFERRED_TO_INVESTIGATION") {
    return "danger";
  }
  if (status === "APPROVED" || status === "DERIVED_VERSION_READY") return "warning";
  return "neutral";
}

function verifyLineageProjection(
  report: AgentTaskLineageReport,
  focusTaskId: string,
): string | undefined {
  if (report.focus_task_id !== focusTaskId) {
    return "Lineage focus_task_id 与当前选中任务不一致，已拒绝绘制。";
  }
  if (report.node_count !== report.nodes.length || report.edge_count !== report.edges.length) {
    return "Lineage 计数与节点 / 边数组不一致，已拒绝绘制。";
  }
  const nodeIds = new Set(report.nodes.map((node) => node.task_id));
  if (
    nodeIds.size !== report.nodes.length ||
    !nodeIds.has(report.root_task_id) ||
    !nodeIds.has(report.focus_task_id) ||
    !nodeIds.has(report.latest_task_id)
  ) {
    return "Lineage 根、焦点或最新任务绑定不完整，已拒绝绘制。";
  }
  const invalidEdge = report.edges.find((edge) => {
    const child = report.nodes.find((node) => node.task_id === edge.child_task_id);
    return (
      !nodeIds.has(edge.parent_task_id) ||
      !child ||
      child.parent_task_id !== edge.parent_task_id ||
      child.depth !== edge.depth ||
      edge.root_task_id !== report.root_task_id ||
      edge.contract_sha256 !== report.contract_sha256
    );
  });
  return invalidEdge
    ? `Lineage edge ${invalidEdge.child_task_id} 的节点或合同绑定不一致，已拒绝绘制。`
    : undefined;
}

function capaChildBinding(
  capa: AgentCapaLineageRecord,
  report: AgentTaskLineageReport,
): "MATCHED" | "HOLD" | "NOT_CREATED" {
  if (!capa.execution) return "NOT_CREATED";
  return report.edges.some(
    (edge) =>
      edge.parent_task_id === capa.parent_task_id &&
      edge.child_task_id === capa.execution?.child_task_id,
  )
    ? "MATCHED"
    : "HOLD";
}

function LineageEdgeRow({ edge }: { edge: AgentTaskLineageEdge }) {
  const style = {
    "--live-lineage-depth": Math.min(edge.depth, 8),
  } as CSSProperties;
  return (
    <div className="live-lineage-edge-row" style={style}>
      <span className="live-lineage-edge-line" aria-hidden="true" />
      <RotateCcw size={13} aria-hidden="true" />
      <div>
        <strong>REVERIFICATION · depth {edge.depth}</strong>
        <small>{edge.note}</small>
      </div>
      <code title={edge.edge_sha256}>{shortDigest(edge.edge_sha256)}</code>
      <span>{edge.created_by} · {formatTime(edge.created_at)}</span>
    </div>
  );
}

function TaskGraphNode({
  node,
  task,
  edge,
  incidents,
  capas,
  relationErrors,
  report,
  selected,
  relationsLoading,
  onSelect,
}: {
  node: AgentTaskLineageNode;
  task?: AgentTask;
  edge?: AgentTaskLineageEdge;
  incidents: IndustrialIncident[];
  capas: AgentCapaLineageRecord[];
  relationErrors: string[];
  report: AgentTaskLineageReport;
  selected: boolean;
  relationsLoading: boolean;
  onSelect: () => void;
}) {
  const style = {
    "--live-lineage-depth": Math.min(node.depth, 8),
  } as CSSProperties;
  const NodeIcon = node.execution_status === "FAILED" ? XCircle : node.depth ? RotateCcw : Database;

  return (
    <div className="live-lineage-branch" style={style}>
      {edge ? <LineageEdgeRow edge={edge} /> : null}
      <button
        type="button"
        className={`live-lineage-task-node${selected ? " is-selected" : ""}${
          node.execution_status === "FAILED" ? " is-failed" : ""
        }`}
        onClick={onSelect}
      >
        <span className="live-lineage-node-icon"><NodeIcon size={16} /></span>
        <span className="live-lineage-node-copy">
          <span>
            <strong>{node.depth === 0 ? "Parent / Root Task" : `Child Run · depth ${node.depth}`}</strong>
            {node.is_focus ? <em>FOCUS</em> : null}
            {node.task_id === report.latest_task_id ? <em>LATEST</em> : null}
          </span>
          <code>{node.task_id}</code>
          <small>{task?.goal ?? `${node.source_kind} · ${node.source_id ?? "no source id"}`}</small>
        </span>
        <span className="live-lineage-node-state">
          <StatusBadge tone={taskTone(node.execution_status)} compact>{node.execution_status}</StatusBadge>
          <b>{node.final_decision ?? "NO DECISION"}</b>
        </span>
        <span className="live-lineage-node-hash">
          <Hash size={11} /> request {shortDigest(node.request_sha256, 8)}
        </span>
      </button>

      <div className="live-lineage-related-rail">
        {relationsLoading ? (
          <div className="live-lineage-related-empty"><LoaderCircle className="is-spinning" size={12} /> 正在读取关联账本</div>
        ) : null}

        {!relationsLoading && incidents.map((incident) => {
          const incidentFailedWorkers = incident.worker_receipts.filter(
            (receipt) => receipt.status === "FAILED",
          );
          return (
            <article className={`live-lineage-related-node is-incident${incidentFailedWorkers.length ? " is-failed" : ""}`} key={incident.case_id}>
              <Bot size={14} />
              <div>
                <span><strong>Incident v5/v6</strong><small>独立 API · task_id binding</small></span>
                <code>{incident.case_id}</code>
                <p>{incident.recommendation_reason}</p>
              </div>
              <StatusBadge tone={incidentFailedWorkers.length ? "danger" : "info"} compact>{incident.status}</StatusBadge>
              <span>{incidentFailedWorkers.length ? `${incidentFailedWorkers.length} FAILED WORKER` : `${incident.worker_receipts.length} worker receipts`}</span>
            </article>
          );
        })}

        {!relationsLoading && capas.map((capa) => {
          const childBinding = capaChildBinding(capa, report);
          return (
            <article className="live-lineage-related-node is-capa" key={capa.case_id}>
              <Workflow size={14} />
              <div>
                <span><strong>CAPA Case</strong><small>独立 API · parent_task_id binding</small></span>
                <code>{capa.case_id}</code>
                <p>{capa.approval ? `由 ${capa.approval.approved_by} 具名批准` : "尚无具名批准绑定"}</p>
              </div>
              <StatusBadge tone={capaTone(capa.status)} compact>{capa.status}</StatusBadge>
              <span className={`is-binding-${childBinding.toLowerCase()}`}>
                {childBinding === "MATCHED"
                  ? "CAPA → Child edge MATCHED"
                  : childBinding === "HOLD"
                    ? "HOLD · Child edge 未匹配"
                    : "Child Run 尚未建立"}
              </span>
            </article>
          );
        })}

        {!relationsLoading && incidents.length === 0 && capas.length === 0 && relationErrors.length === 0 ? (
          <div className="live-lineage-related-empty">
            <CircleDot size={11} /> 此 Task 尚无持久化 Incident v5/v6 或 CAPA Case
          </div>
        ) : null}

        {relationErrors.map((message) => (
          <div className="live-lineage-related-error" key={message}>
            <AlertTriangle size={12} /> {message}
          </div>
        ))}
      </div>
    </div>
  );
}

export function LineagePage() {
  const { activeWorkspace, activeProject, connection, workspaceLoading } = useProduct();
  const [searchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [lineage, setLineage] = useState<AgentTaskLineageReport>();
  const [related, setRelated] = useState<RelatedRecords>(emptyRelated);
  const [taskLoading, setTaskLoading] = useState(false);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [relationsLoading, setRelationsLoading] = useState(false);
  const [scopeError, setScopeError] = useState<string>();
  const [lineageError, setLineageError] = useState<string>();
  const [scopeNotice, setScopeNotice] = useState<string>();
  const [query, setQuery] = useState("");
  const [refreshRevision, setRefreshRevision] = useState(0);
  const scopeGenerationRef = useRef(0);
  const detailGenerationRef = useRef(0);

  const workspaceId = activeWorkspace?.workspace_id;
  const projectId = activeProject?.project_id;

  useEffect(() => {
    const generation = ++scopeGenerationRef.current;
    detailGenerationRef.current += 1;
    setTasks([]);
    setSelectedTaskId("");
    setSelectedNodeId("");
    setLineage(undefined);
    setRelated(emptyRelated);
    setScopeError(undefined);
    setLineageError(undefined);
    setScopeNotice(undefined);

    if (!workspaceId || !projectId || connection.api !== "CONNECTED") return;
    setTaskLoading(true);
    void listAgentTasks(workspaceId, projectId)
      .then((records) => {
        if (generation !== scopeGenerationRef.current) return;
        const scoped = records.filter(
          (task) => task.workspace_id === workspaceId && task.project_id === projectId,
        );
        if (scoped.length !== records.length) {
          setScopeNotice("API 返回了当前 workspace / project 之外的任务，前端已拒绝显示越界记录。");
        }
        setTasks(scoped);
        const stored = window.sessionStorage.getItem(`visiondata:lineage-task:${projectId}`) ?? "";
        const requested = scoped.find((task) => task.task_id === requestedTaskId);
        if (requestedTaskId && !requested) {
          setScopeNotice((current) => [
            current,
            "深链接 Task 不属于当前 workspace / project，已拒绝定位。",
          ].filter(Boolean).join(" "));
        }
        setSelectedTaskId(requestedTaskId
          ? (requested?.task_id ?? "")
          : (
              scoped.find((task) => task.task_id === stored)?.task_id ??
              scoped[0]?.task_id ??
              ""
            ));
      })
      .catch((error) => {
        if (generation === scopeGenerationRef.current) setScopeError(readableError(error));
      })
      .finally(() => {
        if (generation === scopeGenerationRef.current) setTaskLoading(false);
      });
  }, [connection.api, projectId, refreshRevision, requestedTaskId, workspaceId]);

  useEffect(() => {
    const scopeGeneration = scopeGenerationRef.current;
    const detailGeneration = ++detailGenerationRef.current;
    setLineage(undefined);
    setRelated(emptyRelated);
    setLineageError(undefined);
    setSelectedNodeId("");
    if (!selectedTaskId || !projectId || !workspaceId || connection.api !== "CONNECTED") return;

    window.sessionStorage.setItem(`visiondata:lineage-task:${projectId}`, selectedTaskId);
    setLineageLoading(true);
    void getAgentTaskLineage(selectedTaskId)
      .then(async (report) => {
        if (
          scopeGeneration !== scopeGenerationRef.current ||
          detailGeneration !== detailGenerationRef.current
        ) return;
        const projectionError = verifyLineageProjection(report, selectedTaskId);
        if (projectionError) throw new Error(projectionError);
        setLineage(report);
        setSelectedNodeId(report.focus_task_id);
        setLineageLoading(false);
        setRelationsLoading(true);

        const rows = await Promise.all(report.nodes.map(async (node) => {
          const [incidentResult, capaResult] = await Promise.allSettled([
            listIndustrialIncidentV5(node.task_id),
            listAgentCapaLineageRecords(node.task_id),
          ]);
          const errors: string[] = [];
          const incidents = incidentResult.status === "fulfilled"
            ? incidentResult.value.filter((incident) => incident.task_id === node.task_id)
            : [];
          const capas = capaResult.status === "fulfilled"
            ? capaResult.value.filter((capa) => capa.parent_task_id === node.task_id)
            : [];
          if (incidentResult.status === "rejected") errors.push(`Incident v5/v6: ${readableError(incidentResult.reason)}`);
          if (capaResult.status === "rejected") errors.push(`CAPA: ${readableError(capaResult.reason)}`);
          return { taskId: node.task_id, incidents, capas, errors };
        }));

        if (
          scopeGeneration !== scopeGenerationRef.current ||
          detailGeneration !== detailGenerationRef.current
        ) return;
        setRelated({
          incidentsByTask: Object.fromEntries(rows.map((row) => [row.taskId, row.incidents])),
          capasByTask: Object.fromEntries(rows.map((row) => [row.taskId, row.capas])),
          errorsByTask: Object.fromEntries(rows.map((row) => [row.taskId, row.errors])),
        });
        setRelationsLoading(false);
      })
      .catch((error) => {
        if (
          scopeGeneration !== scopeGenerationRef.current ||
          detailGeneration !== detailGenerationRef.current
        ) return;
        setLineageError(readableError(error));
        setLineageLoading(false);
        setRelationsLoading(false);
      });
  }, [connection.api, projectId, selectedTaskId, workspaceId]);

  const tasksById = useMemo(
    () => Object.fromEntries(tasks.map((task) => [task.task_id, task])),
    [tasks],
  );
  const visibleTasks = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return tasks;
    return tasks.filter((task) =>
      [task.task_id, task.goal, task.execution_status, task.final_decision ?? ""]
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [query, tasks]);
  const selectedNode = lineage?.nodes.find((node) => node.task_id === selectedNodeId);
  const selectedEdge = selectedNode?.parent_task_id
    ? lineage?.edges.find((edge) => edge.child_task_id === selectedNode.task_id)
    : undefined;
  const selectedIncidents = selectedNode ? related.incidentsByTask[selectedNode.task_id] ?? [] : [];
  const selectedCapas = selectedNode ? related.capasByTask[selectedNode.task_id] ?? [] : [];
  const selectedTask = selectedNode ? tasksById[selectedNode.task_id] : undefined;
  const matchedCapaChildCount = lineage
    ? selectedCapas.filter((capa) => capaChildBinding(capa, lineage) === "MATCHED").length
    : 0;

  return (
    <div className="live-lineage-page">
      <header className="live-lineage-header">
        <div>
          <span className="live-lineage-kicker"><GitBranch size={13} /> TASK LINEAGE / PROVENANCE</span>
          <h1>执行血缘工作台</h1>
          <p>读取真实 Task、重验边、Incident v5/v6 与 CAPA 绑定；没有持久化关系时保持空白或 HOLD。</p>
          <div className="live-lineage-header-meta">
            <EvidenceSourceBadge source={connection.api === "CONNECTED" ? "LIVE_API" : "NOT_CONNECTED"} />
            <span>{activeWorkspace?.name ?? "未选择工作空间"}</span>
            <span>/</span>
            <strong>{activeProject?.name ?? "未选择项目"}</strong>
            {activeProject?.source_kind === "synthetic_demo" ? <StatusBadge tone="info" compact>SAMPLE SCOPE</StatusBadge> : null}
          </div>
        </div>
        <ActionButton
          variant="secondary"
          icon={RefreshCw}
          disabled={taskLoading || connection.api !== "CONNECTED"}
          onClick={() => setRefreshRevision((value) => value + 1)}
        >
          刷新真实账本
        </ActionButton>
      </header>

      {scopeNotice ? <div className="live-lineage-notice"><ShieldAlert size={14} /> {scopeNotice}</div> : null}

      <div className="live-lineage-workbench">
        <aside className="live-lineage-inbox">
          <header>
            <div><span>PROJECT TASKS</span><strong>{tasks.length}</strong></div>
            <small>{projectId ?? "no project scope"}</small>
          </header>
          <label className="live-lineage-search">
            <Search size={13} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Task / goal / status" />
          </label>
          <div className="live-lineage-task-list">
            {taskLoading || workspaceLoading ? (
              <div className="live-lineage-loading"><LoaderCircle className="is-spinning" size={16} /> 正在读取项目任务</div>
            ) : null}
            {!taskLoading && scopeError ? (
              <EmptyState icon={ShieldAlert} title="任务账本读取失败" description={scopeError} />
            ) : null}
            {!taskLoading && !scopeError && connection.api !== "CONNECTED" ? (
              <EmptyState icon={Database} title="本地 API 未连接" description="不会回退到 fixture；连接 API 后再读取真实 Task。" />
            ) : null}
            {!taskLoading && !scopeError && connection.api === "CONNECTED" && !activeProject ? (
              <EmptyState icon={Workflow} title="未选择项目" description="请先在左侧 IDE 项目树中选择一个真实项目。" />
            ) : null}
            {!taskLoading && !scopeError && activeProject && tasks.length === 0 ? (
              <EmptyState icon={GitBranch} title="项目暂无 Task" description="在 Agent 中心创建并运行任务后，血缘会从真实账本出现。" />
            ) : null}
            {visibleTasks.map((task) => (
              <button
                type="button"
                key={task.task_id}
                className={`${task.task_id === selectedTaskId ? "is-active" : ""}${task.execution_status === "FAILED" ? " is-failed" : ""}`}
                onClick={() => setSelectedTaskId(task.task_id)}
              >
                <i />
                <span><strong>{task.goal}</strong><code>{task.task_id}</code></span>
                <StatusBadge tone={taskTone(task.execution_status)} compact>{task.execution_status}</StatusBadge>
                <small>{task.final_decision ?? task.current_phase} · {formatTime(task.updated_at)}</small>
              </button>
            ))}
            {tasks.length > 0 && visibleTasks.length === 0 ? (
              <p className="live-lineage-no-results">没有匹配的真实 Task</p>
            ) : null}
          </div>
          <footer>
            <LockKeyhole size={12} /> 只读投影 · 不修改 Parent 或 Child 证据
          </footer>
        </aside>

        <main className="live-lineage-canvas">
          <header className="live-lineage-canvas-toolbar">
            <div>
              <span><GitBranch size={13} /> RUN FAMILY</span>
              <strong>{lineage ? `${lineage.node_count} nodes · ${lineage.edge_count} sealed edges` : "选择 Task 查看执行族"}</strong>
            </div>
            {lineage ? (
              <div>
                <StatusBadge tone={lineage.nodes.some((node) => node.execution_status === "FAILED") ? "danger" : "success"} compact>
                  {lineage.nodes.some((node) => node.execution_status === "FAILED") ? "FAILED NODE PRESENT" : "SERVER VALIDATED"}
                </StatusBadge>
                <code>{lineage.schema_version}</code>
              </div>
            ) : null}
          </header>

          <div className="live-lineage-canvas-body">
            {lineageLoading ? (
              <div className="live-lineage-canvas-loading">
                <LoaderCircle className="is-spinning" size={20} />
                <strong>正在核验 Task lineage</strong>
                <small>读取节点、边与 hash-sealed report</small>
              </div>
            ) : null}
            {!lineageLoading && lineageError ? (
              <EmptyState icon={ShieldAlert} title="血缘不可用" description={`${lineageError}；前端未推断或补画关系。`} />
            ) : null}
            {!lineageLoading && !lineageError && !selectedTaskId ? (
              <EmptyState icon={GitBranch} title="没有可绘制的 Task" description="选择左侧真实 Task；当前项目为空时这里不会显示演示节点。" />
            ) : null}
            {lineage ? (
              <div className="live-lineage-graph" aria-label="真实 Task 血缘图">
                <div className="live-lineage-contract-strip">
                  <FileKey2 size={13} />
                  <span><small>FROZEN CONTRACT SHA-256</small><code title={lineage.contract_sha256}>{lineage.contract_sha256}</code></span>
                  <StatusBadge tone="info" compact>SAME CONTRACT FAMILY</StatusBadge>
                </div>
                {lineage.nodes.map((node) => (
                  <TaskGraphNode
                    key={node.task_id}
                    node={node}
                    task={tasksById[node.task_id]}
                    edge={lineage.edges.find((edge) => edge.child_task_id === node.task_id)}
                    incidents={related.incidentsByTask[node.task_id] ?? []}
                    capas={related.capasByTask[node.task_id] ?? []}
                    relationErrors={related.errorsByTask[node.task_id] ?? []}
                    report={lineage}
                    selected={node.task_id === selectedNodeId}
                    relationsLoading={relationsLoading}
                    onSelect={() => setSelectedNodeId(node.task_id)}
                  />
                ))}
                <div className="live-lineage-report-seal">
                  <ShieldCheck size={15} />
                  <span><strong>LINEAGE REPORT SHA-256</strong><code title={lineage.report_sha256}>{lineage.report_sha256}</code></span>
                  <small>由服务端 hash-sealed projection 返回</small>
                </div>
              </div>
            ) : null}
          </div>
        </main>

        <aside className="live-lineage-inspector">
          <header>
            <div><span>INSPECTOR</span><strong>{selectedNode ? (selectedNode.depth ? "Child Run" : "Parent Task") : "No selection"}</strong></div>
            <Hash size={14} />
          </header>
          {!selectedNode || !lineage ? (
            <EmptyState icon={Link2} title="选择一个节点" description="节点、边、人工闸门与声明边界会显示在这里。" />
          ) : (
            <div className="live-lineage-inspector-body">
              <section className="live-lineage-inspector-section">
                <div className="live-lineage-section-title"><Database size={13} /><strong>Task contract</strong></div>
                <dl>
                  <div><dt>task id</dt><dd title={selectedNode.task_id}>{selectedNode.task_id}</dd></div>
                  <div><dt>relation</dt><dd>{selectedNode.relation}</dd></div>
                  <div><dt>status</dt><dd><StatusBadge tone={taskTone(selectedNode.execution_status)} compact>{selectedNode.execution_status}</StatusBadge></dd></div>
                  <div><dt>decision</dt><dd>{selectedNode.final_decision ?? "NOT ESTABLISHED"}</dd></div>
                  <div><dt>source</dt><dd>{selectedNode.source_kind}</dd></div>
                  <div><dt>created</dt><dd>{formatTime(selectedNode.created_at)}</dd></div>
                  <div><dt>completed</dt><dd>{formatTime(selectedNode.completed_at)}</dd></div>
                </dl>
                <Digest label="Request SHA-256" value={selectedNode.request_sha256} />
                {selectedNode.evidence_sha256 ? <Digest label="Evidence SHA-256" value={selectedNode.evidence_sha256} /> : (
                  <div className="live-lineage-hold"><AlertTriangle size={12} /> Evidence SHA 尚未生成 · HOLD</div>
                )}
                {selectedEdge ? <Digest label="Edge SHA-256" value={selectedEdge.edge_sha256} /> : null}
              </section>

              <section className="live-lineage-inspector-section">
                <div className="live-lineage-section-title"><UserCheck size={13} /><strong>Human gates</strong></div>
                <div className="live-lineage-gate-row">
                  <span>Task plan approval</span>
                  <StatusBadge tone={selectedTask?.plan_approval_required ? "warning" : "neutral"} compact>
                    {selectedTask ? (selectedTask.plan_approval_required ? "REQUIRED" : "NOT REQUIRED") : "NOT LOADED"}
                  </StatusBadge>
                </div>
                {selectedCapas.map((capa) => (
                  <div className="live-lineage-human-binding" key={capa.case_id}>
                    {capa.approval ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
                    <span>
                      <strong>{capa.approval ? capa.approval.approved_by : "CAPA approval 未建立"}</strong>
                      <small>{capa.approval ? `${formatTime(capa.approval.approved_at)} · ${shortDigest(capa.approval.binding_sha256)}` : capa.case_id}</small>
                    </span>
                  </div>
                ))}
                {selectedCapas.length === 0 ? <div className="live-lineage-hold"><CircleDot size={12} /> 无 CAPA 人工批准记录</div> : null}
                <div className="live-lineage-release-lock"><LockKeyhole size={13} /><span><strong>Production release</strong><small>human_only · lineage 不授予放行权</small></span><StatusBadge tone="danger" compact>FALSE</StatusBadge></div>
              </section>

              <section className="live-lineage-inspector-section">
                <div className="live-lineage-section-title"><ShieldCheck size={13} /><strong>Proof coverage</strong></div>
                <div className="live-lineage-proof-row is-proven"><span>Task parent → child</span><b>{selectedEdge ? "SEALED EDGE" : "ROOT"}</b></div>
                <div className={`live-lineage-proof-row ${selectedIncidents.length ? "is-bound" : "is-hold"}`}><span>Task → Incident v5/v6</span><b>{selectedIncidents.length ? `task_id · ${selectedIncidents.length}` : "NOT ESTABLISHED"}</b></div>
                <div className={`live-lineage-proof-row ${selectedCapas.length ? "is-bound" : "is-hold"}`}><span>Task → CAPA</span><b>{selectedCapas.length ? `parent_task_id · ${selectedCapas.length}` : "NOT ESTABLISHED"}</b></div>
                <div className={`live-lineage-proof-row ${matchedCapaChildCount ? "is-proven" : "is-hold"}`}><span>CAPA → Child Run</span><b>{matchedCapaChildCount ? `${matchedCapaChildCount} MATCHED` : "HOLD"}</b></div>
                <div className="live-lineage-proof-row is-denied"><span>物理整改 / 客户验收 / 生产放行</span><b>NOT PROVEN</b></div>
              </section>

              <section className="live-lineage-inspector-section">
                <div className="live-lineage-section-title"><ShieldCheck size={13} /><strong>Report seals</strong></div>
                <Digest label="Contract SHA-256" value={lineage.contract_sha256} />
                <Digest label="Report SHA-256" value={lineage.report_sha256} />
              </section>

              {selectedIncidents.map((incident) => (
                <ClaimBoundary key={incident.case_id} title={`Incident ${incident.case_id}`} tone="info">
                  {incident.claim_boundary}
                </ClaimBoundary>
              ))}
            </div>
          )}
        </aside>
      </div>

      <ClaimBoundary title="Lineage API 的原始声明边界" tone="info">
        {lineage?.claim_boundary ?? "尚未读取真实 lineage report。页面不会用 fixture 填充 Parent、Incident、CAPA 或 Child Run。"}
      </ClaimBoundary>
    </div>
  );
}
