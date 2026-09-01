import {
  AlertTriangle,
  ArrowRight,
  Bot,
  BrainCircuit,
  BriefcaseBusiness,
  CheckCircle2,
  CircleOff,
  Clock3,
  FileUp,
  FileSearch,
  Filter,
  GitBranch,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldCheck,
  Siren,
  UserCheck,
  Wrench,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type {
  AgentTask,
  Goal3HandoffReceipt,
  IndustrialIncident,
} from "../agentDomain";
import { useProduct } from "../ProductContext";
import {
  createIndustrialIncident,
  getGoal3HandoffReceipt,
  listAgentTasks,
  listIndustrialIncidentV5,
  listProviderProfiles,
} from "../data/api";
import {
  ClaimBoundary,
  EvidenceSourceBadge,
  Modal,
  PageIntro,
  StatusBadge,
} from "../components/ui";
import type { ProviderProfileRecord, StatusTone } from "../domain";

type CaseFilter = "ALL" | "BLOCKING" | "WORKER_FAILED" | "UNRESOLVED";
type LoadState = "IDLE" | "LOADING" | "READY" | "ERROR";

interface LiveCaseRow {
  key: string;
  task: AgentTask;
  incident: IndustrialIncident;
}

interface TaskLoadFailure {
  taskId: string;
  message: string;
}

const filters: Array<{ value: CaseFilter; label: string }> = [
  { value: "ALL", label: "全部" },
  { value: "BLOCKING", label: "阻断证据" },
  { value: "WORKER_FAILED", label: "Worker 失败" },
  { value: "UNRESOLVED", label: "信念未决" },
];

const incidentRequestSchemas = new Set([
  "visiondata-gate.industrial-incident-request.v1",
  "visiondata-gate.industrial-incident-request.v2",
  "visiondata-gate.industrial-incident-request.v3",
]);

function compactId(value: string, head = 10, tail = 6): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "未知 API 错误";
}

function statusTone(value: string): StatusTone {
  const normalized = value.toUpperCase();
  if (/FAILED|BLOCKED|STOPPED|HOLD|REJECT/.test(normalized)) return "danger";
  if (/PENDING|WAIT|RECAPTURE|REVIEW|PLANNED/.test(normalized)) return "warning";
  if (/COMPLETED|PASS|SUCCEEDED|SUPPORTED|CURRENT/.test(normalized)) return "success";
  if (/RUNNING|VERIFYING|DISPATCHED|CREATED/.test(normalized)) return "info";
  return "neutral";
}

function blockingIssues(incident: IndustrialIncident) {
  return incident.evidence_issues.filter(
    (issue) => issue.severity === "BLOCKING" || issue.blocks_disposition,
  );
}

function failedWorkers(incident: IndustrialIncident) {
  return incident.worker_receipts.filter((receipt) => receipt.status === "FAILED");
}

function unresolvedCount(incident: IndustrialIncident): number {
  return incident.planning_belief_ledger.snapshots.reduce(
    (total, snapshot) => total + snapshot.unresolved_evidence_count,
    0,
  );
}

function openTask(row: LiveCaseRow): void {
  window.sessionStorage.setItem(
    `visiondata:agent-task:${row.task.project_id}`,
    row.task.task_id,
  );
}

function parseIncidentRequest(value: string): Record<string, unknown> {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("事件请求必须是一个 JSON 对象。");
  }
  const payload = parsed as Record<string, unknown>;
  if (
    typeof payload.schema_version !== "string" ||
    !incidentRequestSchemas.has(payload.schema_version)
  ) {
    throw new Error("仅接受 industrial-incident-request v1 / v2 / v3 合同。");
  }
  return payload;
}

async function importIdempotencyKey(taskId: string, payloadText: string): Promise<string> {
  const input = new TextEncoder().encode(`${taskId}\u0000${payloadText.trim()}`);
  const digest = await crypto.subtle.digest("SHA-256", input);
  const hex = Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, "0")).join("");
  return `web-incident-import-${hex.slice(0, 48)}`;
}

function IncidentImportDialog({
  tasks,
  handoffs,
  providerProfiles,
  initialTaskId,
  onClose,
  onCreated,
}: {
  tasks: AgentTask[];
  handoffs: Record<string, Goal3HandoffReceipt>;
  providerProfiles: ProviderProfileRecord[];
  initialTaskId?: string;
  onClose: () => void;
  onCreated: (incident: IndustrialIncident) => void;
}) {
  const [taskId, setTaskId] = useState(
    tasks.find((task) => task.task_id === initialTaskId)?.task_id
      ?? tasks[0]?.task_id
      ?? "",
  );
  const [payloadText, setPayloadText] = useState("");
  const [fileName, setFileName] = useState("");
  const [providerSelection, setProviderSelection] = useState("contract");
  const [attested, setAttested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const selectedTask = tasks.find((task) => task.task_id === taskId);
  const selectedHandoff = taskId ? handoffs[taskId] : undefined;

  useEffect(() => textAreaRef.current?.focus(), []);

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    setError(undefined);
    if (file.size > 2 * 1024 * 1024) {
      setError("JSON 文件超过 2 MiB，本地工作台已拒绝加载。");
      return;
    }
    try {
      const value = await file.text();
      parseIncidentRequest(value);
      setPayloadText(value);
      setFileName(file.name);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const canSubmit = Boolean(
    taskId &&
    payloadText.trim() &&
    attested &&
    !submitting &&
    selectedHandoff?.handoff_status === "READY_FOR_INCIDENT_INTAKE" &&
    selectedHandoff.incident_intake_permitted,
  );
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(undefined);
    try {
      const payload = parseIncidentRequest(payloadText);
      if (payload.operator_attests_inputs_authorized !== true) {
        throw new Error("请求合同必须显式包含 operator_attests_inputs_authorized=true。");
      }
      let finalPayload = payload;
      if (providerSelection !== "contract") {
        if (payload.schema_version !== "visiondata-gate.industrial-incident-request.v3") {
          throw new Error("模型运行配置只属于 v3 合同；请升级事件请求后再选择客户模型。");
        }
        if (providerSelection === "deterministic-off") {
          finalPayload = {
            ...payload,
            runtime_profile: {
              model_profile_id: "deterministic-off",
              planner_mode: "off",
            },
          };
        } else {
          const selectedProfile = providerProfiles.find(
            (profile) => profile.profile_id === providerSelection,
          );
          if (!selectedProfile) {
            throw new Error("所选客户模型配置已失效，请刷新后重新选择。");
          }
          finalPayload = {
            ...payload,
            runtime_profile: {
              model_profile_id: "workspace-byok",
              provider_profile_id: selectedProfile.profile_id,
              planner_mode: selectedProfile.default_planner_mode,
              max_output_tokens: selectedProfile.max_output_tokens,
              context_budget_tokens: selectedProfile.context_budget_tokens,
            },
          };
        }
      }
      const serializedFinalPayload = JSON.stringify(finalPayload);
      if (!selectedTask) {
        throw new Error("所选 Task 已不在当前项目作用域，已拒绝导入。");
      }
      const currentHandoff = await getGoal3HandoffReceipt(taskId);
      if (
        currentHandoff.workspace_id !== selectedTask.workspace_id ||
        currentHandoff.project_id !== selectedTask.project_id ||
        currentHandoff.task_request_sha256 !== selectedTask.request_sha256
      ) {
        throw new Error("Goal3 handoff 与当前 Task 作用域或请求摘要不一致。");
      }
      if (
        currentHandoff.handoff_status !== "READY_FOR_INCIDENT_INTAKE" ||
        !currentHandoff.incident_intake_permitted
      ) {
        throw new Error(`Goal → Goal3 交接已阻断：${currentHandoff.next_action}`);
      }
      const idempotencyKey = await importIdempotencyKey(
        taskId,
        serializedFinalPayload,
      );
      const created = await createIndustrialIncident(
        taskId,
        finalPayload,
        idempotencyKey,
        currentHandoff.receipt_sha256,
      );
      onCreated(created);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="导入受控工业事件" onClose={submitting ? () => undefined : onClose}>
      <form className="agent-create-form incident-import-form" onSubmit={(event) => void submit(event)}>
        <div className="agent-create-form__scope">
          <span>LOCAL JSON → VALIDATED INCIDENT V5/V6</span>
          <strong>离线证据合同导入</strong>
          <small>仅提交到本机 API；服务端执行完整 schema、哈希、时间窗与权限边界校验。</small>
        </div>

        <label className="agent-form-field">
          <span>绑定已完成 Task</span>
          <select value={taskId} onChange={(event) => setTaskId(event.target.value)} required>
            {tasks.map((task) => (
              <option value={task.task_id} key={task.task_id}>
                {task.task_id} · {task.final_decision ?? task.execution_status}
              </option>
            ))}
          </select>
          <small>Incident 会绑定该 Task 的不可变执行身份；不会覆盖 Task 证据。</small>
        </label>

        <section className="incident-import-handoff" aria-label="Goal 到 Goal3 交接回执">
          <header>
            <span><ShieldCheck size={14} /> GOAL → GOAL3 HANDOFF</span>
            <StatusBadge
              tone={selectedHandoff?.handoff_status === "READY_FOR_INCIDENT_INTAKE" ? "success" : "danger"}
              compact
            >
              {selectedHandoff?.handoff_status ?? "UNAVAILABLE"}
            </StatusBadge>
          </header>
          <div className="agent-goal3-handoff__rail">
            <span className={selectedHandoff?.task_execution_status === "COMPLETED" ? "is-complete" : ""}>
              <i>01</i><strong>Goal Task</strong><small>{selectedHandoff?.task_execution_status ?? "UNAVAILABLE"}</small>
            </span>
            <span className={selectedHandoff?.task_evidence_integrity === "VERIFIED" ? "is-complete" : ""}>
              <i>02</i><strong>证据交接</strong><small>{selectedHandoff?.task_evidence_integrity ?? "UNAVAILABLE"}</small>
            </span>
            <span className={selectedHandoff?.incident_intake_permitted ? "is-ready" : ""}>
              <i>03</i><strong>Goal3 Kernel</strong><small>{selectedHandoff?.incident_intake_permitted ? "INTAKE READY" : "HOLD"}</small>
            </span>
          </div>
          <p>{selectedHandoff?.next_action ?? "未取得可验证的交接回执，导入保持禁用。"}</p>
          {selectedHandoff ? (
            <code title={selectedHandoff.receipt_sha256}>
              HANDOFF SHA · {compactId(selectedHandoff.receipt_sha256, 12, 8)}
            </code>
          ) : null}
        </section>

        <label className="agent-form-field incident-provider-select">
          <span>本次案件使用的规划模型</span>
          <select
            value={providerSelection}
            onChange={(event) => setProviderSelection(event.target.value)}
            disabled={submitting}
          >
            <option value="contract">按导入 JSON 合同执行</option>
            <option value="deterministic-off">确定性内核 · 不调用模型</option>
            {providerProfiles.map((profile) => (
              <option value={profile.profile_id} key={profile.profile_id}>
                {profile.display_name} · {profile.model}
                {profile.is_default ? " · 默认" : ""}
              </option>
            ))}
          </select>
          <small>
            选择客户模型后，v3 请求会绑定该用户在当前工作区的 Provider Profile ID；API Key 不进入案件 JSON。
          </small>
        </label>

        <label className="agent-form-field incident-import-file">
          <span>选择离线事件 JSON</span>
          <input
            type="file"
            accept="application/json,.json"
            onChange={(event) => void loadFile(event.target.files?.[0])}
          />
          <small>{fileName || "支持 v1 / v2 / v3；最大 2 MiB。也可以直接在下方粘贴。"}</small>
        </label>

        <label className="agent-form-field">
          <span>事件请求合同</span>
          <textarea
            ref={textAreaRef}
            value={payloadText}
            onChange={(event) => {
              setPayloadText(event.target.value);
              setFileName("");
            }}
            rows={11}
            spellCheck={false}
            placeholder='{"schema_version":"visiondata-gate.industrial-incident-request.v3", ...}'
            required
          />
          <small>前端只做合同版本与 JSON 形状检查；专业约束由后端确定性验证，错误不会降级放行。</small>
        </label>

        <label className={`agent-attestation${attested ? " is-checked" : ""}`}>
          <input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} />
          <ShieldCheck size={16} />
          <span>
            <strong>我确认有权使用该离线导出，且已检查脱敏范围</strong>
            <small>导入只创建受控 Incident；不连接真实 OPC UA、MES、PLC 或 VisionMaster，也不授予生产放行权。</small>
          </span>
        </label>

        {error ? <div className="agent-form-error" role="alert">{error}</div> : null}
        <footer>
          <button type="button" onClick={onClose} disabled={submitting}>取消</button>
          <button className="is-primary" type="submit" disabled={!canSubmit}>
            {submitting ? <LoaderCircle className="is-spinning" size={14} /> : <FileUp size={14} />}
            {submitting ? "正在验证并建立案件…" : "验证并导入"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

export function CasesPage() {
  const {
    activeWorkspace,
    activeProject,
    connection,
    workspaceLoading,
  } = useProduct();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const requestedCaseId = searchParams.get("case")?.trim() ?? "";
  const requestedVersion = searchParams.get("version")?.trim() ?? "";
  const requestedImport = searchParams.get("import") === "1";
  const [rows, setRows] = useState<LiveCaseRow[]>([]);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [goal3Handoffs, setGoal3Handoffs] = useState<Record<string, Goal3HandoffReceipt>>({});
  const [handoffFailures, setHandoffFailures] = useState<TaskLoadFailure[]>([]);
  const [providerProfiles, setProviderProfiles] = useState<ProviderProfileRecord[]>([]);
  const [taskCount, setTaskCount] = useState(0);
  const [selectedKey, setSelectedKey] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CaseFilter>("ALL");
  const [loadState, setLoadState] = useState<LoadState>("IDLE");
  const [loadError, setLoadError] = useState<string>();
  const [selectionNotice, setSelectionNotice] = useState<string>();
  const [partialFailures, setPartialFailures] = useState<TaskLoadFailure[]>([]);
  const [refreshToken, setRefreshToken] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const loadGeneration = useRef(0);
  const importDeepLinkRef = useRef("");

  useEffect(() => {
    const workspaceId = activeWorkspace?.workspace_id;
    setProviderProfiles([]);
    if (!workspaceId || connection.api !== "CONNECTED") return;
    let active = true;
    void listProviderProfiles(workspaceId)
      .then((profiles) => {
        if (active) setProviderProfiles(profiles.filter((item) => item.status === "ACTIVE"));
      })
      .catch(() => {
        if (active) setProviderProfiles([]);
      });
    return () => {
      active = false;
    };
  }, [activeWorkspace?.workspace_id, connection.api]);

  useEffect(() => {
    const generation = loadGeneration.current + 1;
    loadGeneration.current = generation;
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;

    setRows([]);
    setTasks([]);
    setGoal3Handoffs({});
    setHandoffFailures([]);
    setTaskCount(0);
    setSelectedKey("");
    setPartialFailures([]);
    setLoadError(undefined);
    setSelectionNotice(undefined);

    if (!workspaceId || !projectId || connection.api !== "CONNECTED") {
      setLoadState("IDLE");
      return;
    }

    setLoadState("LOADING");
    void (async () => {
      try {
        const tasks = await listAgentTasks(workspaceId, projectId);
        if (loadGeneration.current !== generation) return;

        const scopedTasks = tasks.filter(
          (task) => task.workspace_id === workspaceId && task.project_id === projectId,
        );
        setTasks(scopedTasks);
        setTaskCount(scopedTasks.length);

        const results = await Promise.allSettled(
          scopedTasks.map(async (task) => ({
            task,
            incidents: await listIndustrialIncidentV5(task.task_id),
          })),
        );
        const handoffResults = await Promise.allSettled(
          scopedTasks.map((task) => getGoal3HandoffReceipt(task.task_id)),
        );
        if (loadGeneration.current !== generation) return;

        const nextRows: LiveCaseRow[] = [];
        const nextFailures: TaskLoadFailure[] = [];
        const nextHandoffs: Record<string, Goal3HandoffReceipt> = {};
        const nextHandoffFailures: TaskLoadFailure[] = [];
        results.forEach((result, index) => {
          if (result.status === "rejected") {
            const task = scopedTasks[index];
            nextFailures.push({
              taskId: task?.task_id ?? "unknown-task",
              message: errorMessage(result.reason),
            });
            return;
          }
          result.value.incidents.forEach((incident) => {
            if (incident.task_id !== result.value.task.task_id) return;
            nextRows.push({
              key: `${incident.case_id}:${incident.case_version}:${result.value.task.task_id}`,
              task: result.value.task,
              incident,
            });
          });
        });

        handoffResults.forEach((result, index) => {
          const task = scopedTasks[index];
          if (!task) return;
          if (result.status === "rejected") {
            nextHandoffFailures.push({
              taskId: task.task_id,
              message: errorMessage(result.reason),
            });
            return;
          }
          const handoff = result.value;
          if (
            handoff.workspace_id !== workspaceId ||
            handoff.project_id !== projectId ||
            handoff.task_id !== task.task_id ||
            handoff.task_request_sha256 !== task.request_sha256
          ) {
            nextHandoffFailures.push({
              taskId: task.task_id,
              message: "交接回执与当前 workspace / project / Task 摘要不一致",
            });
            return;
          }
          nextHandoffs[task.task_id] = handoff;
        });

        nextRows.sort(
          (left, right) =>
            new Date(right.task.updated_at).getTime() -
              new Date(left.task.updated_at).getTime() ||
            right.incident.case_version - left.incident.case_version,
        );
        setRows(nextRows);
        setPartialFailures(nextFailures);
        setGoal3Handoffs(nextHandoffs);
        setHandoffFailures(nextHandoffFailures);
        const hasDeepLink = Boolean(
          requestedCaseId || requestedVersion || (requestedTaskId && !requestedImport),
        );
        const requested = hasDeepLink
          ? nextRows.find((row) => (
              (!requestedTaskId || row.task.task_id === requestedTaskId) &&
              (!requestedCaseId || row.incident.case_id === requestedCaseId) &&
              (!requestedVersion || String(row.incident.case_version) === requestedVersion)
            ))
          : undefined;
        if (hasDeepLink && !requested) {
          setSelectedKey("");
          setSelectionNotice(
            "深链接 Incident 不属于当前 workspace / project，或指定版本不存在；已拒绝展示其他案件作为替代。",
          );
        } else {
          setSelectedKey(requested?.key ?? nextRows[0]?.key ?? "");
        }
        setLoadState("READY");
      } catch (error) {
        if (loadGeneration.current !== generation) return;
        setLoadError(errorMessage(error));
        setLoadState("ERROR");
      }
    })();

    return () => {
      if (loadGeneration.current === generation) loadGeneration.current += 1;
    };
  }, [
    activeProject?.project_id,
    activeWorkspace?.workspace_id,
    connection.api,
    refreshToken,
    requestedCaseId,
    requestedTaskId,
    requestedVersion,
    requestedImport,
  ]);

  const visibleRows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return rows.filter((row) => {
      const { incident, task } = row;
      const matchesFilter =
        filter === "ALL" ||
        (filter === "BLOCKING" && blockingIssues(incident).length > 0) ||
        (filter === "WORKER_FAILED" && failedWorkers(incident).length > 0) ||
        (filter === "UNRESOLVED" && unresolvedCount(incident) > 0);
      const matchesQuery =
        !normalized ||
        [
          incident.case_id,
          incident.status,
          incident.recommendation,
          incident.recommendation_reason,
          task.task_id,
          task.goal,
          ...incident.worker_selection_receipt.selected_worker_ids,
        ]
          .join(" ")
          .toLowerCase()
          .includes(normalized);
      return matchesFilter && matchesQuery;
    });
  }, [filter, query, rows]);

  useEffect(() => {
    if (selectionNotice || visibleRows.some((row) => row.key === selectedKey)) return;
    setSelectedKey(visibleRows[0]?.key ?? "");
  }, [selectedKey, selectionNotice, visibleRows]);

  const selected = visibleRows.find((row) => row.key === selectedKey);
  const importableTasks = useMemo(
    () => tasks.filter((task) => {
      const handoff = goal3Handoffs[task.task_id];
      return (
        task.execution_status === "COMPLETED" &&
        handoff?.handoff_status === "READY_FOR_INCIDENT_INTAKE" &&
        handoff.incident_intake_permitted
      );
    }),
    [goal3Handoffs, tasks],
  );

  useEffect(() => {
    if (!requestedImport || loadState !== "READY") return;
    const requested = requestedTaskId
      ? importableTasks.find((task) => task.task_id === requestedTaskId)
      : importableTasks[0];
    const requestedHandoff = requestedTaskId ? goal3Handoffs[requestedTaskId] : undefined;
    const handoffIdentity = requestedHandoff?.receipt_sha256 ?? "unavailable";
    const deepLinkKey = `${activeProject?.project_id ?? ""}:${requestedTaskId || "first"}:${handoffIdentity}`;
    if (importDeepLinkRef.current === deepLinkKey) return;
    importDeepLinkRef.current = deepLinkKey;
    if (!requested) {
      const handoffFailure = handoffFailures.find((item) => item.taskId === requestedTaskId);
      setSelectionNotice(
        `Goal → Goal3 交接被拒绝：${requestedHandoff?.next_action ?? handoffFailure?.message ?? "指定 Task 不属于当前项目、尚未完成，或证据入口不可用。"}`,
      );
      return;
    }
    setSelectionNotice(undefined);
    setImportOpen(true);
  }, [
    activeProject?.project_id,
    goal3Handoffs,
    handoffFailures,
    importableTasks,
    loadState,
    requestedImport,
    requestedTaskId,
  ]);
  const totalBlocking = rows.reduce(
    (total, row) => total + blockingIssues(row.incident).length,
    0,
  );
  const totalFailures = rows.reduce(
    (total, row) => total + failedWorkers(row.incident).length,
    0,
  );
  const totalUnresolved = rows.reduce(
    (total, row) => total + unresolvedCount(row.incident),
    0,
  );

  const noScope = !activeWorkspace || !activeProject;
  const apiUnavailable = connection.api !== "CONNECTED";

  return (
    <div className="page-stack live-cases-page">
      <PageIntro
        eyebrow="CASES / INCIDENT V5/V6"
        title="工业案件收件箱"
        description="只汇总当前项目真实 Task 产生的 Incident v5/v6；信念账本、Worker 选择、失败回执与人工闸门均直接来自服务端。"
        meta={
          <>
            <EvidenceSourceBadge
              source={connection.api === "CONNECTED" ? "LIVE_API" : "NOT_CONNECTED"}
            />
            <span>{activeWorkspace?.name ?? "未选择工作空间"}</span>
            <span>/</span>
            <strong>{activeProject?.name ?? "未选择项目"}</strong>
          </>
        }
        actions={
          <div className="live-cases-page-actions">
            <button
              className="live-cases-refresh"
              type="button"
              disabled={importableTasks.length === 0 || noScope || apiUnavailable}
              title={importableTasks.length === 0 ? "当前没有通过 Goal3 handoff 完整性闸门的 Task" : "导入已授权的离线工业事件 JSON"}
              onClick={() => setImportOpen(true)}
            >
              <FileUp size={14} />
              导入工业事件
            </button>
            <button
              className="live-cases-refresh"
              type="button"
              disabled={loadState === "LOADING" || noScope || apiUnavailable}
              onClick={() => setRefreshToken((value) => value + 1)}
            >
              <RefreshCw
                size={14}
                className={loadState === "LOADING" ? "is-spinning" : ""}
              />
              刷新账本
            </button>
          </div>
        }
      />

      <section className="live-cases-stats" aria-label="真实案件摘要">
        <article>
          <BriefcaseBusiness size={15} />
          <span>Incident v5/v6</span>
          <strong>{rows.length}</strong>
          <small>来自 {taskCount} 个当前项目 Task</small>
        </article>
        <article className={totalBlocking > 0 ? "is-warning" : ""}>
          <Siren size={15} />
          <span>阻断证据</span>
          <strong>{totalBlocking}</strong>
          <small>blocks disposition</small>
        </article>
        <article className={totalFailures > 0 ? "is-danger" : ""}>
          <XCircle size={15} />
          <span>Worker 失败</span>
          <strong>{totalFailures}</strong>
          <small>FAILED receipts</small>
        </article>
        <article className={totalUnresolved > 0 ? "is-warning" : ""}>
          <BrainCircuit size={15} />
          <span>未决证据引用</span>
          <strong>{totalUnresolved}</strong>
          <small>belief ledger v2</small>
        </article>
      </section>

      {partialFailures.length > 0 ? (
        <details className="live-cases-partial-warning">
          <summary>
            <AlertTriangle size={14} />
            {partialFailures.length} 个 Task 的 Incident 接口读取失败；其案件未计入当前列表
          </summary>
          {partialFailures.map((failure) => (
            <p key={failure.taskId}>
              <code>{failure.taskId}</code>
              <span>{failure.message}</span>
            </p>
          ))}
        </details>
      ) : null}

      {handoffFailures.length > 0 ? (
        <details className="live-cases-partial-warning is-danger">
          <summary>
            <LockKeyhole size={14} />
            {handoffFailures.length} 个 Task 的 Goal3 交接回执不可验证；导入入口保持关闭
          </summary>
          {handoffFailures.map((failure) => (
            <p key={failure.taskId}>
              <code>{failure.taskId}</code>
              <span>{failure.message}</span>
            </p>
          ))}
        </details>
      ) : null}

      {selectionNotice ? (
        <div className="live-cases-partial-warning">
          <AlertTriangle size={14} /> {selectionNotice}
        </div>
      ) : null}

      <section className="live-cases-workbench">
        <aside className="live-cases-inbox">
          <header>
            <div>
              <span>CASE INBOX</span>
              <strong>案件</strong>
            </div>
            <small>{visibleRows.length} / {rows.length}</small>
          </header>

          <label className="live-cases-search">
            <Search size={13} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索案件、任务或 Worker"
            />
          </label>

          <div className="live-cases-filters" aria-label="案件筛选">
            <Filter size={12} />
            {filters.map((item) => (
              <button
                key={item.value}
                type="button"
                className={filter === item.value ? "is-active" : ""}
                onClick={() => setFilter(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="live-cases-list">
            {loadState === "LOADING" ? (
              <div className="live-cases-list-state">
                <LoaderCircle className="is-spinning" size={17} />
                <strong>读取案件账本</strong>
                <small>先读取当前项目 Task，再逐项核对 Incident v5/v6。</small>
              </div>
            ) : visibleRows.length > 0 ? (
              visibleRows.map((row) => {
                const blocking = blockingIssues(row.incident).length;
                const failed = failedWorkers(row.incident).length;
                const unresolved = unresolvedCount(row.incident);
                return (
                  <button
                    type="button"
                    key={row.key}
                    className={selected?.key === row.key ? "is-active" : ""}
                    onClick={() => {
                      setSelectionNotice(undefined);
                      setSelectedKey(row.key);
                    }}
                  >
                    <span className={`live-cases-state-dot is-${statusTone(row.incident.status)}`} />
                    <div>
                      <strong title={row.incident.case_id}>
                        {compactId(row.incident.case_id, 12, 5)}
                      </strong>
                      <p>{row.task.goal}</p>
                      <small>
                        v{row.incident.case_version} · {formatTime(row.task.updated_at)}
                      </small>
                    </div>
                    <span className="live-cases-row-alerts">
                      {blocking > 0 ? <em className="is-warning">B{blocking}</em> : null}
                      {failed > 0 ? <em className="is-danger">F{failed}</em> : null}
                      {unresolved > 0 ? <em>U{unresolved}</em> : null}
                    </span>
                    <ArrowRight size={13} />
                  </button>
                );
              })
            ) : (
              <div className="live-cases-list-state">
                <FileSearch size={18} />
                <strong>{rows.length > 0 ? "没有匹配案件" : "当前没有 Incident v5/v6"}</strong>
                <small>
                  {rows.length > 0
                    ? "调整筛选条件或搜索词。"
                    : "这里不会用样例案件补位。"}
                </small>
              </div>
            )}
          </div>
        </aside>

        <main className="live-cases-canvas">
          {workspaceLoading || loadState === "LOADING" ? (
            <div className="live-cases-empty">
              <LoaderCircle className="is-spinning" size={21} />
              <strong>正在建立当前项目案件视图</strong>
              <p>所有结果都将绑定当前 workspace / project 作用域。</p>
            </div>
          ) : apiUnavailable ? (
            <div className="live-cases-empty is-danger">
              <CircleOff size={22} />
              <strong>本地 API 未连接</strong>
              <p>案件页保持空白，不回退到冻结 fixture。</p>
            </div>
          ) : noScope ? (
            <div className="live-cases-empty">
              <BriefcaseBusiness size={22} />
              <strong>请先选择工作空间与项目</strong>
              <p>案件查询严格跟随左侧项目作用域。</p>
            </div>
          ) : loadState === "ERROR" ? (
            <div className="live-cases-empty is-danger">
              <AlertTriangle size={22} />
              <strong>案件账本读取失败</strong>
              <p>{loadError ?? "服务端未返回可验证结果。"}</p>
              <button type="button" onClick={() => setRefreshToken((value) => value + 1)}>
                <RefreshCw size={13} /> 重试
              </button>
            </div>
          ) : !selected ? (
            <div className="live-cases-empty">
              <Bot size={22} />
              <strong>{taskCount > 0 ? "当前 Task 尚未绑定 Incident v5/v6" : "先创建并运行一个受控 Agent 任务"}</strong>
              <p>
                {taskCount > 0
                  ? "可导入已授权的离线 OPC UA、视觉方案与运行回执 JSON；服务端验证通过后才建立案件。"
                  : "完成计划审批与确定性工具执行后，再通过受控导入建立工业案件。"}
              </p>
              {importableTasks.length > 0 ? (
                <button className="live-cases-primary-link" type="button" onClick={() => setImportOpen(true)}>
                  导入工业事件 <FileUp size={13} />
                </button>
              ) : (
                <Link className="live-cases-primary-link" to="/command-center">
                  打开 Agent 工作台 <ArrowRight size={13} />
                </Link>
              )}
            </div>
          ) : (
            <>
              <header className="live-cases-case-header">
                <div>
                  <span>{selected.incident.schema_version.endsWith(".v6") ? "INCIDENT V6" : "INCIDENT V5"} · CASE {selected.incident.case_version}</span>
                  <h2>{selected.incident.case_id}</h2>
                  <p>{selected.task.goal}</p>
                </div>
                <div>
                  <StatusBadge tone={statusTone(selected.incident.status)} compact>
                    {selected.incident.status}
                  </StatusBadge>
                  <StatusBadge tone={statusTone(selected.task.execution_status)} compact>
                    TASK {selected.task.execution_status}
                  </StatusBadge>
                  <Link
                    className="live-cases-open-workbench"
                    to={`/cases/${encodeURIComponent(selected.incident.case_id)}?task=${encodeURIComponent(selected.task.task_id)}`}
                  >
                    进入案件工作台 <ArrowRight size={13} />
                  </Link>
                </div>
              </header>

              <section className="live-cases-recommendation">
                <header>
                  <Bot size={14} />
                  <span>可审计建议</span>
                  <code>{selected.incident.planning_mode}</code>
                </header>
                <strong>{selected.incident.recommendation}</strong>
                <p>{selected.incident.recommendation_reason}</p>
                <small>
                  root cause: {selected.incident.root_cause_status} · external model calls: {selected.incident.external_model_call_count}
                </small>
              </section>

              <section className="live-cases-belief">
                <header>
                  <div>
                    <BrainCircuit size={14} />
                    <span>EVIDENCE BELIEF LEDGER V2</span>
                  </div>
                  <code title={selected.incident.planning_belief_ledger.ledger_sha256}>
                    {compactId(selected.incident.planning_belief_ledger.ledger_sha256, 8, 6)}
                  </code>
                </header>
                <div className="live-cases-belief-metrics">
                  <span><strong>{selected.incident.planning_belief_ledger.hypothesis_count}</strong><small>hypotheses</small></span>
                  <span><strong>{selected.incident.planning_belief_ledger.evidence_edge_count}</strong><small>evidence edges</small></span>
                  <span className={unresolvedCount(selected.incident) > 0 ? "is-warning" : ""}><strong>{unresolvedCount(selected.incident)}</strong><small>unresolved refs</small></span>
                  <span><strong>{selected.incident.planning_belief_ledger.source_authorization_freshness.freshness_status}</strong><small>source freshness</small></span>
                </div>
                <div className="live-cases-belief-list">
                  {selected.incident.planning_belief_ledger.snapshots.length > 0 ? (
                    selected.incident.planning_belief_ledger.snapshots.map((snapshot) => (
                      <article key={snapshot.snapshot_sha256}>
                        <span className={`live-cases-state-dot is-${statusTone(snapshot.support_status)}`} />
                        <div>
                          <strong>{snapshot.hypothesis_id}</strong>
                          <small>
                            source {snapshot.source_hypothesis_status} · freshness {snapshot.freshness_status}
                          </small>
                        </div>
                        <StatusBadge tone={statusTone(snapshot.support_status)} compact>
                          {snapshot.support_status}
                        </StatusBadge>
                        <em>{snapshot.unresolved_evidence_count} unresolved</em>
                      </article>
                    ))
                  ) : (
                    <p className="live-cases-inline-empty">账本未返回 hypothesis snapshot。</p>
                  )}
                </div>
              </section>

              <section className="live-cases-actions-ledger">
                <header>
                  <GitBranch size={14} />
                  <span>AGENT ACTIONS</span>
                  <small>{selected.incident.agent_actions.length} 条持久化动作</small>
                </header>
                <div>
                  {selected.incident.agent_actions.map((action) => (
                    <article key={`${action.sequence}:${action.agent_role}`}>
                      <span>{String(action.sequence).padStart(2, "0")}</span>
                      <div>
                        <strong>{action.action}</strong>
                        <p>{action.agent_role} · iteration {action.iteration}</p>
                      </div>
                      <StatusBadge tone={statusTone(action.status)} compact>{action.status}</StatusBadge>
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </main>

        <aside className="live-cases-inspector">
          {selected ? (
            <>
              <section className="live-cases-safety">
                <header><ShieldCheck size={14} /> HUMAN AUTHORITY</header>
                <div>
                  <span><UserCheck size={12} /> 人工批准</span>
                  <strong>{selected.incident.human_approval_required ? "REQUIRED" : "NOT REQUIRED"}</strong>
                </div>
                <div>
                  <LockKeyhole size={12} />
                  <span>生产放行</span>
                  <strong className="is-locked">{String(selected.incident.production_release_allowed).toUpperCase()}</strong>
                </div>
                <div>
                  <CircleOff size={12} />
                  <span>设备写入</span>
                  <strong className="is-locked">{String(selected.incident.machine_write_permitted).toUpperCase()}</strong>
                </div>
              </section>

              <section className="live-cases-inspector-section">
                <header>
                  <Wrench size={13} />
                  <span>WORKER SELECTION</span>
                  <small>{selected.incident.worker_selection_receipt.selected_worker_ids.length} selected</small>
                </header>
                <div className="live-cases-worker-ranking">
                  {selected.incident.worker_selection_receipt.ranking.length > 0 ? (
                    [...selected.incident.worker_selection_receipt.ranking]
                      .sort((left, right) => (left.rank ?? 999) - (right.rank ?? 999))
                      .map((worker) => (
                        <article className={worker.selected ? "is-selected" : ""} key={worker.worker_id}>
                          <span>{worker.rank ?? "—"}</span>
                          <div>
                            <strong>{worker.worker_id}</strong>
                            <small>
                              {worker.selected
                                ? "selected by deterministic receipt"
                                : worker.exclusion_reasons.join(" · ") || "not selected"}
                            </small>
                          </div>
                          {worker.selected ? <CheckCircle2 size={13} /> : <CircleOff size={12} />}
                        </article>
                      ))
                  ) : (
                    <p className="live-cases-inline-empty">未返回 Worker ranking。</p>
                  )}
                </div>
              </section>

              <section className="live-cases-inspector-section">
                <header>
                  <Siren size={13} />
                  <span>EVIDENCE ISSUES</span>
                  <small>{selected.incident.evidence_issues.length}</small>
                </header>
                <div className="live-cases-issues">
                  {selected.incident.evidence_issues.length > 0 ? (
                    selected.incident.evidence_issues.map((issue, index) => (
                      <article
                        key={`${issue.issue_code}:${index}`}
                        className={issue.severity === "BLOCKING" ? "is-blocking" : ""}
                      >
                        <div>
                          <StatusBadge tone={issue.severity === "BLOCKING" ? "danger" : "warning"} compact>
                            {issue.severity}
                          </StatusBadge>
                          <code>{issue.issue_code}</code>
                        </div>
                        <strong>{issue.summary}</strong>
                        <p>{issue.required_evidence_or_action}</p>
                        <small>{issue.worker_role} · blocks {String(issue.blocks_disposition)}</small>
                      </article>
                    ))
                  ) : (
                    <p className="live-cases-inline-empty">服务端未报告 evidence issue。</p>
                  )}
                </div>
              </section>

              <section className="live-cases-inspector-section">
                <header>
                  <XCircle size={13} />
                  <span>WORKER RECEIPTS</span>
                  <small>{selected.incident.worker_receipts.length}</small>
                </header>
                <div className="live-cases-receipts">
                  {selected.incident.worker_receipts.length > 0 ? (
                    selected.incident.worker_receipts.map((receipt) => (
                      <article className={receipt.status === "FAILED" ? "is-failed" : ""} key={receipt.invocation_id}>
                        <div>
                          <strong>{receipt.worker_role}</strong>
                          <StatusBadge tone={receipt.status === "FAILED" ? "danger" : "success"} compact>
                            {receipt.status}
                          </StatusBadge>
                        </div>
                        <small>attempt {receipt.attempt} · {compactId(receipt.invocation_id, 10, 5)}</small>
                        {receipt.status === "FAILED" ? (
                          <p>
                            <b>{receipt.error_code ?? "WORKER_EXECUTION_FAILED"}</b>
                            retryable: {String(receipt.retryable)}
                          </p>
                        ) : null}
                      </article>
                    ))
                  ) : (
                    <p className="live-cases-inline-empty">尚未产生 Worker receipt。</p>
                  )}
                </div>
              </section>

              <section className="live-cases-safe-entry">
                <header><Clock3 size={13} /> 受控操作入口</header>
                <p>收件箱保持只读；具名决定、CAPA 选择与补证恢复在案件工作台执行。</p>
                <Link to={`/cases/${encodeURIComponent(selected.incident.case_id)}?task=${encodeURIComponent(selected.task.task_id)}`}>
                  打开案件工作台 <ArrowRight size={13} />
                </Link>
                <Link to="/command-center" onClick={() => openTask(selected)}>
                  打开对应 Task <ArrowRight size={13} />
                </Link>
                <small title={selected.task.task_id}>{selected.task.task_id}</small>
              </section>
            </>
          ) : (
            <div className="live-cases-empty is-compact">
              <LockKeyhole size={20} />
              <strong>没有可检查的真实案件</strong>
              <p>安全边界仍然生效：production release = false。</p>
            </div>
          )}
        </aside>
      </section>

      <ClaimBoundary title="案件页声明边界" tone="danger">
        本页不加载 fixture，也不执行放行或设备写入。Incident v5/v6 结论仍需人工复核；
        production_release_allowed=false 不会因页面展示而改变。
      </ClaimBoundary>

      {importOpen ? (
        <IncidentImportDialog
          tasks={importableTasks}
          handoffs={goal3Handoffs}
          providerProfiles={providerProfiles}
          initialTaskId={requestedTaskId || undefined}
          onClose={() => {
            setImportOpen(false);
            if (requestedImport) {
              const next = new URLSearchParams(searchParams);
              next.delete("import");
              if (!next.has("case") && !next.has("version")) next.delete("task");
              setSearchParams(next, { replace: true });
            }
          }}
          onCreated={(incident) => {
            setImportOpen(false);
            setSearchParams(
              {
                task: incident.task_id,
                case: incident.case_id,
                version: String(incident.case_version),
              },
              { replace: true },
            );
            setRefreshToken((value) => value + 1);
          }}
        />
      ) : null}
    </div>
  );
}
