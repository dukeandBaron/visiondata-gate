import {
  Activity,
  AlertCircle,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  DatabaseZap,
  FileCheck2,
  GitMerge,
  Inbox,
  ListChecks,
  LoaderCircle,
  LockKeyhole,
  Plus,
  RadioTower,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserCheck,
  Waypoints,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type {
  AgentIntervention,
  AgentInterventionAction,
  AgentReleaseReadiness,
  AgentRuntimeCapabilities,
  AgentTask,
  AgentTaskEvent,
  AgentTaskPlan,
  AgentTaskPreflight,
  GovernedIncidentContext,
  Goal3HandoffReceipt,
  HostedAgentTeamsReceipt,
  IndustrialIncident,
  LocalTaskSource,
  PublicAgentTool,
} from "../agentDomain";
import { publicAgentTools } from "../agentDomain";
import { useProduct } from "../ProductContext";
import {
  createAgentIntervention,
  createAgentReverification,
  createAgentTask,
  getAgentReleaseReadiness,
  getAgentRuntimeCapabilities,
  getAgentTask,
  getAgentTaskPlan,
  getAgentTaskPreflight,
  getGoal3HandoffReceipt,
  getIndustrialIncidentGovernedContext,
  listAgentInterventions,
  listAgentTaskEvents,
  listAgentTasks,
  listIndustrialIncidentV5,
  listLocalTaskSources,
  operatorActorUserId,
  submitHostedAgentTeamsTask,
} from "../data/api";
import type { ProjectRecord, StatusTone, WorkspaceRecord } from "../domain";
import { ActionButton, EmptyState, Modal, Panel, StatusBadge } from "../components/ui";

const toolLabels: Record<PublicAgentTool, string> = {
  image_quality: "图像质量",
  duplicate_leakage: "重复与泄漏",
  annotation_integrity: "标注完整性",
  coverage_matrix: "覆盖矩阵",
  governance_audit: "治理审计",
};

const interventionLabels: Record<AgentInterventionAction, string> = {
  approve_plan: "批准计划",
  cancel_plan: "取消计划",
  acknowledge_result: "确认已审阅结果",
  request_changes: "请求补证 / 修改",
};

type InboxFilter = "ALL" | "HUMAN" | "RUNNING" | "DONE";
const hostedApprovalIdPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

interface AgentTaskDetail {
  task: AgentTask;
  plan?: AgentTaskPlan;
  preflight?: AgentTaskPreflight;
  events: AgentTaskEvent[];
  interventions: AgentIntervention[];
  incidents: IndustrialIncident[];
  releaseReadiness?: AgentReleaseReadiness;
  goal3Handoff?: Goal3HandoffReceipt;
  governedContext?: GovernedIncidentContext;
  unavailable: string[];
}

interface InlineFeedback {
  tone: "success" | "danger" | "info";
  message: string;
}

function formatTime(value: string | null): string {
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

function shortDigest(value: string | null | undefined): string {
  return value ? `${value.slice(0, 9)}…${value.slice(-6)}` : "尚未生成";
}

function readableError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "本地 API 请求失败";
}

function taskTone(task: AgentTask): StatusTone {
  if (task.execution_status === "COMPLETED") return "success";
  if (task.execution_status === "FAILED") return "danger";
  if (task.execution_status === "CANCELLED" || task.execution_status === "ARCHIVED") {
    return "locked";
  }
  if (task.execution_status === "PLANNED" && task.plan_approval_required) return "warning";
  return "info";
}

function checkTone(status: AgentTaskPreflight["checks"][number]["status"]): StatusTone {
  if (status === "PASS") return "success";
  if (status === "BLOCKED") return "danger";
  if (status === "PENDING") return "warning";
  return "neutral";
}

function TaskCreationDialog({
  workspace,
  project,
  preferredSourceId,
  onClose,
  onCreated,
}: {
  workspace: WorkspaceRecord;
  project: ProjectRecord;
  preferredSourceId?: string;
  onClose: () => void;
  onCreated: (task: AgentTask) => void;
}) {
  const [goal, setGoal] = useState(
    preferredSourceId
      ? "审核当前工作簿不可变快照，执行确定性数据治理并生成可追溯门禁结果。"
      : "",
  );
  const [allowedTools, setAllowedTools] = useState<Set<PublicAgentTool>>(
    () => new Set(publicAgentTools),
  );
  const [planApprovalRequired, setPlanApprovalRequired] = useState(true);
  const [sources, setSources] = useState<LocalTaskSource[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [sourceLoading, setSourceLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const goalRef = useRef<HTMLTextAreaElement>(null);
  const submissionIdentityRef = useRef({ fingerprint: "", key: "" });

  useEffect(() => goalRef.current?.focus(), []);

  useEffect(() => {
    if (project.source_kind !== "local_authorized_directory") return;
    let active = true;
    setSourceLoading(true);
    void listLocalTaskSources(workspace.workspace_id)
      .then((items) => {
        if (!active) return;
        const available = items.filter((item) => item.status === "active");
        setSources(available);
        setSourceId(
          available.find((item) => item.source_id === preferredSourceId)?.source_id
            ?? available[0]?.source_id
            ?? "",
        );
      })
      .catch((caught) => {
        if (active) setError(`无法读取本地授权来源：${readableError(caught)}`);
      })
      .finally(() => {
        if (active) setSourceLoading(false);
      });
    return () => {
      active = false;
    };
  }, [preferredSourceId, project.source_kind, workspace.workspace_id]);

  const toggleTool = (tool: PublicAgentTool) => {
    setAllowedTools((current) => {
      const next = new Set(current);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      return next;
    });
  };

  const sourceBlocked =
    project.source_kind === "external_residency_reference" ||
    (project.source_kind === "local_authorized_directory" && !sourceId);
  const canSubmit =
    goal.trim().length >= 8 && allowedTools.size > 0 && !sourceBlocked && !submitting;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(undefined);
    try {
      const payloadFingerprint = JSON.stringify({
        projectId: project.project_id,
        goal: goal.trim(),
        scenarioProfile: project.scenario_profile,
        sourceKind: project.source_kind,
        sourceId,
        planApprovalRequired,
        allowedTools: publicAgentTools.filter((tool) => allowedTools.has(tool)),
      });
      if (submissionIdentityRef.current.fingerprint !== payloadFingerprint) {
        submissionIdentityRef.current = {
          fingerprint: payloadFingerprint,
          key: `web-task-${crypto.randomUUID()}`,
        };
      }
      const created = await createAgentTask({
        projectId: project.project_id,
        goal: goal.trim(),
        scenarioProfile: project.scenario_profile,
        sourceKind: project.source_kind,
        sourceId: sourceId || undefined,
        planApprovalRequired,
        allowedTools: publicAgentTools.filter((tool) => allowedTools.has(tool)),
        idempotencyKey: submissionIdentityRef.current.key,
      });
      onCreated(created);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="创建 Agent 任务" onClose={submitting ? () => undefined : onClose}>
      <form className="agent-create-form" onSubmit={(event) => void submit(event)}>
        <div className="agent-create-form__scope">
          <span>真实执行范围</span>
          <strong>{workspace.name} / {project.name}</strong>
          <small>{project.source_kind}</small>
        </div>
        <label className="agent-form-field">
          <span>任务目标</span>
          <textarea
            ref={goalRef}
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            rows={4}
            minLength={8}
            maxLength={1200}
            placeholder="例如：核验本批次图像质量、跨划分泄漏和标注完整性，并给出可审计门禁结果。"
            required
          />
          <small>目标会写入不可变任务请求；不能用聊天文本替代范围合同。</small>
        </label>

        <fieldset className="agent-tool-picker">
          <legend>允许调用的确定性工具</legend>
          {publicAgentTools.map((tool) => (
            <label key={tool} className={allowedTools.has(tool) ? "is-selected" : ""}>
              <input
                type="checkbox"
                checked={allowedTools.has(tool)}
                onChange={() => toggleTool(tool)}
              />
              <Wrench size={13} />
              <span><strong>{toolLabels[tool]}</strong><small>{tool}</small></span>
            </label>
          ))}
        </fieldset>

        {project.source_kind === "local_authorized_directory" ? (
          <label className="agent-form-field">
            <span>本地授权来源</span>
            <select
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              disabled={sourceLoading}
              required
            >
              <option value="">{sourceLoading ? "正在读取…" : "请选择有效来源"}</option>
              {sources.map((source) => (
                <option value={source.source_id} key={source.source_id}>
                  {source.display_name}
                </option>
              ))}
            </select>
            {!sourceLoading && sources.length === 0 ? (
              <small className="is-danger">当前工作空间没有 active 本地授权来源，任务保持不可创建。</small>
            ) : null}
          </label>
        ) : null}

        {project.source_kind === "external_residency_reference" ? (
          <div className="agent-inline-notice is-danger">
            <LockKeyhole size={15} /> 外部驻留来源尚未连接，系统按合同拒绝创建任务。
          </div>
        ) : null}

        <label className={`agent-attestation${planApprovalRequired ? " is-checked" : ""}`}>
          <input
            type="checkbox"
            checked={planApprovalRequired}
            onChange={(event) => setPlanApprovalRequired(event.target.checked)}
          />
          <UserCheck size={16} />
          <span>
            <strong>工具执行前必须人工批准 Plan</strong>
            <small>默认开启。关闭后，任务创建成功即会尝试运行确定性工具。</small>
          </span>
        </label>

        {sources.find((source) => source.source_id === sourceId) ? (
          <div className="agent-inline-notice">
            <ShieldCheck size={15} />
            <span>
              已选择 {sources.find((source) => source.source_id === sourceId)?.adapter_kind}
              {" · "}binding {shortDigest(sources.find((source) => source.source_id === sourceId)?.source_archive_sha256 ?? "")}
            </span>
          </div>
        ) : null}
        {error ? <div className="agent-form-error" role="alert">{error}</div> : null}
        <footer>
          <button type="button" onClick={onClose} disabled={submitting}>取消</button>
          <button className="is-primary" type="submit" disabled={!canSubmit}>
            {submitting ? <LoaderCircle className="is-spinning" size={14} /> : <Sparkles size={14} />}
            {submitting ? "正在建立任务…" : "创建受控任务"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function HumanGateDialog({
  action,
  task,
  submitting,
  serverError,
  onClose,
  onSubmit,
}: {
  action: AgentInterventionAction;
  task: AgentTask;
  submitting: boolean;
  serverError?: string;
  onClose: () => void;
  onSubmit: (actorName: string, note: string) => void;
}) {
  const [actorName, setActorName] = useState("");
  const [note, setNote] = useState("");
  const [attested, setAttested] = useState(false);
  const actionLabel = interventionLabels[action];
  const canSubmit = actorName.trim().length >= 2 && note.trim().length >= 2 && attested && !submitting;

  return (
    <Modal title={actionLabel} onClose={submitting ? () => undefined : onClose}>
      <form
        className="agent-gate-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) onSubmit(actorName.trim(), note.trim());
        }}
      >
        <div className="agent-gate-form__binding">
          <UserCheck size={18} />
          <div>
            <span>具名人工动作 · append-only</span>
            <strong>{actionLabel}</strong>
            <small>Task {task.task_id} · {task.execution_status} · {shortDigest(task.request_sha256)}</small>
          </div>
        </div>
        <label className="agent-form-field">
          <span>复核人姓名 / 工号</span>
          <input
            value={actorName}
            onChange={(event) => setActorName(event.target.value)}
            maxLength={120}
            placeholder="例如：QA-017 李工"
            autoFocus
            required
          />
          <small>API 账户同时记录为 {operatorActorUserId}。</small>
        </label>
        <label className="agent-form-field">
          <span>
            {action === "approve_plan"
              ? "批准依据"
              : action === "cancel_plan"
                ? "取消原因"
                : "人工判断与后续要求"}
          </span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={850}
            rows={4}
            placeholder={
              action === "approve_plan"
                ? "说明已核对的数据范围、工具权限、证据缺口与安全边界。"
                : action === "cancel_plan"
                  ? "说明为什么终止该计划；取消后不可继续批准此 Task。"
                : "说明已审阅的证据，以及确认结果或要求补证的具体原因。"
            }
            required
          />
        </label>
        <label className={`agent-attestation${attested ? " is-checked" : ""}`}>
          <input
            type="checkbox"
            checked={attested}
            onChange={(event) => setAttested(event.target.checked)}
          />
          <ShieldCheck size={16} />
          <span>
            <strong>我已复核可见证据并承担本次人工动作责任</strong>
            <small>AI 仅提供诊断与编排建议；本动作不构成生产放行或设备控制授权。</small>
          </span>
        </label>
        {serverError ? <div className="agent-form-error" role="alert">{serverError}</div> : null}
        <footer>
          <button type="button" onClick={onClose} disabled={submitting}>取消</button>
          <button className={action === "request_changes" || action === "cancel_plan" ? "is-danger" : "is-primary"} type="submit" disabled={!canSubmit}>
            {submitting ? <LoaderCircle className="is-spinning" size={14} /> : <UserCheck size={14} />}
            {submitting ? "正在写入审计账本…" : `具名${actionLabel}`}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function ReverificationDialog({
  task,
  submitting,
  serverError,
  onClose,
  onSubmit,
}: {
  task: AgentTask;
  submitting: boolean;
  serverError?: string;
  onClose: () => void;
  onSubmit: (note: string, idempotencyKey: string) => void;
}) {
  const [note, setNote] = useState("");
  const [attested, setAttested] = useState(false);
  const identityRef = useRef({ fingerprint: "", key: "" });
  const canSubmit = note.trim().length >= 4 && attested && !submitting;

  return (
    <Modal title="创建同合同复验 Child Run" onClose={submitting ? () => undefined : onClose}>
      <form
        className="agent-gate-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canSubmit) return;
          const fingerprint = `${task.task_id}:${task.evidence_sha256 ?? "missing"}:${note.trim()}`;
          if (identityRef.current.fingerprint !== fingerprint) {
            identityRef.current = {
              fingerprint,
              key: `web-reverification-${crypto.randomUUID()}`,
            };
          }
          onSubmit(note.trim(), identityRef.current.key);
        }}
      >
        <div className="agent-gate-form__binding">
          <RefreshCw size={18} />
          <div>
            <span>IMMUTABLE PARENT → CHILD RUN</span>
            <strong>父结果不覆盖，Child 使用同一规则合同</strong>
            <small>Parent {task.task_id} · evidence {shortDigest(task.evidence_sha256)}</small>
          </div>
        </div>
        <label className="agent-form-field">
          <span>复验依据 / 发生了什么整改</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            minLength={4}
            maxLength={1000}
            rows={4}
            placeholder="例如：已按工单修订标注，并要求在相同来源快照与冻结合同下复验。"
            autoFocus
            required
          />
        </label>
        <label className={`agent-attestation${attested ? " is-checked" : ""}`}>
          <input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} />
          <ShieldCheck size={16} />
          <span><strong>我确认创建新的 Child Run</strong><small>该动作不会篡改 Parent 证据，也不授予生产放行权限。</small></span>
        </label>
        {serverError ? <div className="agent-form-error" role="alert">{serverError}</div> : null}
        <footer>
          <button type="button" onClick={onClose} disabled={submitting}>取消</button>
          <button className="is-primary" type="submit" disabled={!canSubmit}>
            {submitting ? <LoaderCircle className="is-spinning" size={14} /> : <RefreshCw size={14} />}
            {submitting ? "正在建立 Child Run…" : "创建复验任务"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function HostedAgentTeamsDialog({
  task,
  submitting,
  serverError,
  onClose,
  onSubmit,
}: {
  task: AgentTask;
  submitting: boolean;
  serverError?: string;
  onClose: () => void;
  onSubmit: (approvalId: string) => void;
}) {
  const [approvalId, setApprovalId] = useState("");
  const [attested, setAttested] = useState(false);
  const normalizedApprovalId = approvalId.trim();
  const canSubmit = hostedApprovalIdPattern.test(normalizedApprovalId) && attested && !submitting;

  return (
    <Modal title="提交当前 Task 至 Hosted AgentTeams" onClose={submitting ? () => undefined : onClose}>
      <form
        className="hosted-agentteams-submit-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) onSubmit(normalizedApprovalId);
        }}
      >
        <div className="hosted-submit-binding">
          <RadioTower size={18} />
          <div>
            <span>REMOTE WRITE · EXPLICIT HUMAN GATE</span>
            <strong>{task.task_id}</strong>
            <code>request {shortDigest(task.request_sha256)}</code>
          </div>
        </div>

        <label className="agent-form-field">
          <span>具名 approval_id</span>
          <input
            value={approvalId}
            onChange={(event) => setApprovalId(event.target.value)}
            pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
            placeholder="approval-quality-lead-20260830-01"
            autoComplete="off"
            spellCheck={false}
            autoFocus
            required
          />
          <small>仅允许字母、数字、点、下划线与连字符；该 ID 会绑定到 Hosted 回执。</small>
        </label>

        <div className="hosted-submit-contract">
          <div><span>远程写操作</span><strong>注册项目并发送 Leader ingress</strong></div>
          <div><span>人工确认</span><strong>REQUIRED</strong></div>
          <div><span>wait_for_remote_execution</span><strong>false</strong></div>
          <div><span>生产 / 设备权限</span><strong>NOT GRANTED</strong></div>
        </div>

        <label className={`agent-attestation${attested ? " is-checked" : ""}`}>
          <input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} />
          <ShieldCheck size={16} />
          <span>
            <strong>我确认执行这次远程写操作</strong>
            <small>这是 Hosted 传输提交，不是本地只读 probe；失败或未配置时必须关闭，不自动重试。</small>
          </span>
        </label>

        {serverError ? <div className="agent-form-error" role="alert">{serverError}</div> : null}
        <footer>
          <button type="button" onClick={onClose} disabled={submitting}>保留本地 Task</button>
          <button className="is-primary" type="submit" disabled={!canSubmit}>
            {submitting ? <LoaderCircle className="is-spinning" size={14} /> : <Send size={14} />}
            {submitting ? "正在提交并等待回执…" : "确认远程提交"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function TaskLifecycle({ task }: { task: AgentTask }) {
  const order = ["CREATED", "PLANNED", "RUNNING", "VERIFYING", "COMPLETED"] as const;
  const statusIndex = order.indexOf(task.execution_status as (typeof order)[number]);
  const failed = task.execution_status === "FAILED";
  const cancelled = task.execution_status === "CANCELLED" || task.execution_status === "ARCHIVED";
  return (
    <div className="agent-lifecycle" aria-label="任务阶段">
      {order.map((status, index) => {
        const complete = !failed && !cancelled && statusIndex > index;
        const active = !failed && !cancelled && statusIndex === index;
        const className = complete ? "is-complete" : active ? "is-active" : "";
        return (
          <div className={className} key={status}>
            <span>{complete ? <Check size={11} /> : index + 1}</span>
            <small>{status}</small>
          </div>
        );
      })}
    </div>
  );
}

function Goal2MemoryCard({
  incident,
  context,
  capabilities,
  unavailableReason,
}: {
  incident?: IndustrialIncident;
  context?: GovernedIncidentContext;
  capabilities?: AgentRuntimeCapabilities;
  unavailableReason?: string;
}) {
  const memoryProfiles = capabilities?.memory_profiles ?? [];
  const memoryExpected = Boolean(incident?.governed_memory_retrieval_receipt_sha256);
  const anyAvailable = memoryProfiles.some((profile) => profile.availability === "AVAILABLE");

  if (!context) {
    const status = unavailableReason
      ? "UNAVAILABLE"
      : memoryExpected
      ? "UNAVAILABLE"
      : anyAvailable
        ? "READY / NOT USED"
        : "NOT CONFIGURED";
    return (
      <Panel id="task-memory-proof" className="agent-side-card agent-goal2" variant="subtle">
        <header className="agent-side-card__header">
          <span><DatabaseZap size={14} /> GOAL 2 / GOVERNED MEMORY</span>
          <StatusBadge tone={unavailableReason || memoryExpected ? "danger" : anyAvailable ? "info" : "neutral"} compact>{status}</StatusBadge>
        </header>
        <div className="agent-memory-boundary">
          <BrainCircuit size={18} />
          <div>
            <strong>{unavailableReason ? "知识增强证据当前不可读取" : memoryExpected ? "案件声明了记忆回执，但当前上下文不可读" : "当前案件没有消费受治理历史记忆"}</strong>
            <p>{unavailableReason ?? (memoryExpected ? "页面不补造检索命中；请查看部分只读视图错误。" : "只有 API 返回 SHA 绑定且合同核验通过的上下文时，才展示命中、排序与作用域。")}</p>
          </div>
        </div>
        <div className="agent-memory-profiles">
          {memoryProfiles.length ? memoryProfiles.map((profile) => (
            <div key={profile.profile_id}>
              <i className={`runtime-dot runtime-dot--${profile.availability === "AVAILABLE" ? "connected" : "unavailable"}`} />
              <span><strong>{profile.label}</strong><small>{profile.profile_id} · {profile.availability}</small></span>
            </div>
          )) : <small>Runtime 未返回 memory profile。</small>}
        </div>
        <div className="agent-memory-safety">
          <span><LockKeyhole size={12} /> may_set_current_case_fact=false</span>
          <span><ShieldCheck size={12} /> policy judge input=false</span>
        </div>
      </Panel>
    );
  }

  const retrieval = context.retrieval_receipt;
  const scope = retrieval.query_scope;
  const selected = retrieval.selected;
  const channels = retrieval.channel_receipts ?? [];
  const isV2 = retrieval.schema_version.endsWith(".v2");
  return (
    <Panel id="task-memory-proof" className="agent-side-card agent-goal2" variant="subtle">
      <header className="agent-side-card__header">
        <span><DatabaseZap size={14} /> GOAL 2 / GOVERNED MEMORY</span>
        <StatusBadge tone="success" compact>{isV2 ? "HYBRID V2" : "SCOPED V1"}</StatusBadge>
      </header>

      <section className="agent-memory-scope">
        <header><span>QUERY SCOPE</span><code>{shortDigest(retrieval.query_sha256)}</code></header>
        <div>
          <span><small>site</small><strong>{scope.site_id}</strong></span>
          <span><small>line</small><strong>{scope.line_id ?? "ANY"}</strong></span>
          <span><small>station</small><strong>{scope.station_id ?? "ANY"}</strong></span>
          <span><small>camera</small><strong>{scope.camera_id ?? "ANY"}</strong></span>
        </div>
      </section>

      <section className="agent-memory-retrieval">
        <header>
          <span>RETRIEVAL RECEIPT</span>
          <small>{retrieval.selected_count} selected · {retrieval.rejected_count} rejected</small>
        </header>
        {channels.length ? (
          <div className="agent-memory-channels">
            {channels.map((channel) => (
              <span className={`is-${channel.status.toLowerCase()}`} key={channel.channel} title={channel.warning_code ?? channel.status}>
                <i />{channel.channel}<small>{channel.status}</small>
              </span>
            ))}
          </div>
        ) : <p className="agent-memory-algorithm">SCOPE_THEN_RELEVANCE_V1</p>}
        <div className="agent-memory-counts">
          <span><strong>{retrieval.candidate_count}</strong><small>候选</small></span>
          <span><strong>{retrieval.eligible_count ?? retrieval.candidate_count}</strong><small>合规</small></span>
          <span><strong>{retrieval.selected_count}</strong><small>采用</small></span>
          <span><strong>{retrieval.semantic_status ?? "N/A"}</strong><small>语义通道</small></span>
        </div>
        {retrieval.memory_admission_status ? <p className="agent-memory-admission"><ShieldCheck size={12} /> {retrieval.memory_admission_status}</p> : null}
      </section>

      <section className="agent-memory-hits">
        <header><span>HISTORICAL REFERENCES</span><small>advisory only</small></header>
        {selected.length ? selected.slice(0, 4).map((item) => {
          const reference = context.context.relevant_approved_memories.find((candidate) => candidate.memory_id === item.memory_id);
          return (
            <article key={item.memory_id}>
              <span>{item.rank}</span>
              <div><strong>{reference?.pattern ?? item.memory_id}</strong><p>{reference?.recommended_first_check ?? item.selection_reasons.join(" · ")}</p><small>{item.source_case_ids.join(" · ")} · {shortDigest(item.memory_sha256)}</small></div>
            </article>
          );
        }) : <p>检索成功，但没有历史卡片进入本轮有界上下文。</p>}
      </section>

      <section className="agent-memory-effects">
        <header><Waypoints size={13} /> ALLOWED EFFECTS</header>
        {(context.planning_input?.allowed_effects ?? []).map((effect) => <span key={effect}>{effect.replaceAll("_", " ")}</span>)}
        {!context.planning_input ? <small>planning input unavailable</small> : null}
      </section>

      <div className="agent-memory-safety">
        <span><LockKeyhole size={12} /> current fact authority = none</span>
        <span><ShieldCheck size={12} /> root cause authority = none</span>
        <span><Check size={12} /> cross-site leakage = {context.receipt.cross_site_memory_leakage_count}</span>
      </div>
      <div className="agent-case-digest">MEMORY RECEIPT · {shortDigest(retrieval.receipt_sha256)}</div>
    </Panel>
  );
}

function TaskCapabilityStrip({ detail }: { detail: AgentTaskDetail }) {
  const toolObserved =
    detail.events.some((event) => event.stage.toUpperCase().includes("TOOL")) ||
    detail.incidents.some((incident) => incident.worker_receipts.length > 0);
  const knowledgeUnavailable = detail.unavailable.some(
    (item) => item.startsWith("Incident v5/v6:") || item.startsWith("Governed memory:"),
  );
  const capabilities = [
    { label: "任务理解", status: "BOUND", icon: CircleDot, target: "task-contract", tone: "cyan" },
    { label: "计划生成", status: detail.plan ? "OBSERVED" : "UNAVAILABLE", icon: ListChecks, target: "task-plan", tone: "violet" },
    { label: "工具调用", status: toolObserved ? "OBSERVED" : "NOT RUN", icon: Wrench, target: "task-activity", tone: "lime" },
    { label: "知识增强", status: detail.governedContext ? "GOVERNED" : knowledgeUnavailable ? "UNAVAILABLE" : "NOT USED", icon: DatabaseZap, target: "task-memory-proof", tone: "amber" },
    { label: "人工闸门", status: detail.task.plan_approval_required ? "REQUIRED" : "POLICY BOUND", icon: UserCheck, target: "task-human-gate", tone: "coral" },
    { label: "结果交付", status: detail.releaseReadiness ? "SEALED" : "PENDING", icon: FileCheck2, target: "task-result", tone: "blue" },
  ] as const;
  return (
    <nav className="agent-capability-strip" aria-label="Agent 能力证据索引">
      {capabilities.map((item, index) => (
        <button
          type="button"
          className={`is-${item.tone}`}
          key={item.label}
          onClick={() => document.getElementById(item.target)?.scrollIntoView({ behavior: "smooth", block: "start" })}
        >
          <span>0{index + 1}</span><item.icon size={13} />
          <strong>{item.label}</strong><small>{item.status}</small>
        </button>
      ))}
    </nav>
  );
}

function IncidentGoal3Card({
  incident,
  handoff,
  onOpenIntake,
  onOpenIncident,
  onRequestChanges,
  unavailableReason,
}: {
  incident?: IndustrialIncident;
  handoff?: Goal3HandoffReceipt;
  onOpenIntake: () => void;
  onOpenIncident: () => void;
  onRequestChanges: () => void;
  unavailableReason?: string;
}) {
  if (!incident) {
    const integrityBlocked = Boolean(
      unavailableReason && /(integrity|完整性|\b409\b)/i.test(unavailableReason),
    );
    return (
      <Panel className="agent-side-card agent-goal3-handoff" variant="subtle">
        <header className="agent-side-card__header">
          <span><Waypoints size={14} /> GOAL → GOAL3 HANDOFF</span>
          <StatusBadge
            tone={
              unavailableReason || handoff?.handoff_status.startsWith("BLOCKED")
                ? "danger"
                : handoff?.handoff_status === "READY_FOR_INCIDENT_INTAKE"
                  ? "success"
                  : "neutral"
            }
            compact
          >
            {unavailableReason
              ? integrityBlocked ? "INTEGRITY BLOCKED" : "UNAVAILABLE"
              : handoff?.handoff_status ?? "NO RECEIPT"}
          </StatusBadge>
        </header>
        <div className="agent-goal3-handoff__rail" aria-label="Goal 到 Goal3 的受控交接">
          <span className={handoff?.task_evidence_integrity === "VERIFIED" ? "is-complete" : ""}>
            <i>01</i><strong>Goal Task</strong><small>{handoff?.task_execution_status ?? "UNAVAILABLE"}</small>
          </span>
          <span className={handoff?.incident_intake_permitted ? "is-ready" : ""}>
            <i>02</i><strong>证据交接</strong><small>{handoff?.task_evidence_integrity ?? "UNAVAILABLE"}</small>
          </span>
          <span>
            <i>03</i><strong>Goal3 Kernel</strong><small>WAITING FOR INPUT</small>
          </span>
        </div>
        <div className="agent-goal3-handoff__body">
          {unavailableReason ? <TriangleAlert size={17} /> : <ShieldCheck size={17} />}
          <div>
            <strong>{unavailableReason ? "交接回执不可采信，保持 HOLD" : "尚无真实 Incident Case，不模拟"}</strong>
            <p>{unavailableReason ?? handoff?.next_action ?? "等待服务端返回 Goal3 handoff receipt；前端不会推断入口状态。"}</p>
          </div>
        </div>
        {handoff?.incident_intake_permitted && !unavailableReason ? (
          <ActionButton icon={FileCheck2} onClick={onOpenIntake}>
            导入授权证据并建立 Incident
          </ActionButton>
        ) : null}
        {handoff ? <div className="agent-case-digest">HANDOFF SHA · {shortDigest(handoff.receipt_sha256)}</div> : null}
      </Panel>
    );
  }

  const ledger = incident.planning_belief_ledger;
  const handoffBlocked = Boolean(
    unavailableReason ||
    !handoff ||
    handoff.handoff_status.startsWith("BLOCKED"),
  );
  const selection = incident.worker_selection_receipt;
  const executionPlan = incident.worker_execution_plan_receipt;
  const council = incident.council_arbitration_receipt;
  const autonomy = incident.autonomy_guard_receipt;
  const supportCounts = ledger.snapshots.reduce<Record<string, number>>((counts, snapshot) => {
    counts[snapshot.support_status] = (counts[snapshot.support_status] ?? 0) + 1;
    return counts;
  }, {});
  const failedWorkers = incident.worker_receipts.filter((receipt) => receipt.status === "FAILED");
  const failedActions = incident.agent_actions.filter((action) => action.status === "FAILED");
  const blockingIssues = incident.evidence_issues.filter(
    (issue) => issue.issue_code === "WORKER_EXECUTION_FAILED" || issue.severity === "BLOCKING",
  );
  const hasExecutionFailure = failedWorkers.length > 0 || failedActions.length > 0;

  return (
    <Panel className="agent-side-card agent-goal3" variant={hasExecutionFailure ? "danger" : "subtle"}>
      <header className="agent-side-card__header">
        <span><Sparkles size={14} /> GOAL 3 / {incident.schema_version.endsWith(".v6") ? "INCIDENT V6" : "INCIDENT V5"}</span>
        <StatusBadge tone={hasExecutionFailure || handoffBlocked ? "danger" : "info"} compact>
          {handoffBlocked ? "HANDOFF HOLD" : incident.status}
        </StatusBadge>
      </header>
      {handoffBlocked ? (
        <div className="agent-goal3-integrity-warning" role="alert">
          <TriangleAlert size={15} />
          <div>
            <strong>交接回执不可采信，案件仅保留只读审计入口</strong>
            <p>{unavailableReason ?? handoff?.next_action ?? "Goal3 handoff receipt unavailable."}</p>
          </div>
        </div>
      ) : null}
      <div className="agent-incident-summary">
        <strong>{incident.recommendation}</strong>
        <p>{incident.recommendation_reason}</p>
        <small>root cause: {incident.root_cause_status} · model calls: {incident.external_model_call_count}</small>
      </div>
      <button className="agent-goal3-open-case" type="button" onClick={onOpenIncident}>
        <Waypoints size={13} /> {handoffBlocked ? "只读打开 Goal3 案件审计" : "打开完整 Goal3 案件工作台"} <ChevronRight size={13} />
      </button>

      <section className="agent-belief-ledger">
        <header><span>PLANNING BELIEF LEDGER</span><code>{shortDigest(ledger.ledger_sha256)}</code></header>
        <div className="agent-belief-counts">
          <span className="is-supported"><strong>{supportCounts.SUPPORTED ?? 0}</strong><small>支持</small></span>
          <span className="is-contradicted"><strong>{supportCounts.CONTRADICTED ?? 0}</strong><small>矛盾</small></span>
          <span className="is-unresolved"><strong>{supportCounts.UNRESOLVED ?? 0}</strong><small>未决</small></span>
          <span><strong>{ledger.source_authorization_freshness.freshness_status}</strong><small>新鲜度</small></span>
        </div>
        <div className="agent-belief-list">
          {ledger.snapshots.slice(0, 6).map((snapshot) => (
            <div key={snapshot.hypothesis_id}>
              <span className={`belief-dot is-${snapshot.support_status.toLowerCase()}`} />
              <strong>{snapshot.hypothesis_id}</strong>
              <small>{snapshot.support_status} · {snapshot.freshness_status}</small>
              <em>{snapshot.unresolved_evidence_count} unresolved</em>
            </div>
          ))}
        </div>
      </section>

      <section className="agent-worker-selection">
        <header>
          <span>WORKER SELECTION RECEIPT</span>
          <small>预算 {selection.worker_budget} · 入选 {selection.selected_worker_ids.length}</small>
        </header>
        {selection.ranking.map((entry) => (
          <div className={entry.selected ? "is-selected" : "is-excluded"} key={entry.worker_id}>
            <span>{entry.selected ? <CheckCircle2 size={13} /> : <XCircle size={13} />}</span>
            <strong>{entry.worker_id}</strong>
            <small>
              {entry.selected
                ? `rank ${entry.rank} · blocking ${entry.blocking_severity_rank} · unresolved ${entry.unresolved_evidence_count}`
                : entry.exclusion_reasons.join(" · ") || "未进入本轮预算"}
            </small>
          </div>
        ))}
        <p title={selection.ordering_contract}>确定性排序：资格 → 阻断级别 → 假设区分 → 未决证据 → 成本 → 稳定 ID</p>
      </section>

      {executionPlan ? (
        <section className="agent-kernel-dag">
          <header><span><GitMerge size={12} /> WORKER EXECUTION DAG</span><code>{shortDigest(executionPlan.receipt_sha256)}</code></header>
          <div>
            {executionPlan.execution_order.map((workerId, index) => {
              const node = executionPlan.nodes.find((item) => item.worker_id === workerId);
              return (
                <span key={workerId} title={node?.dependency_worker_ids.length ? `depends on ${node.dependency_worker_ids.join(", ")}` : "no dependency"}>
                  <i>{index + 1}</i><strong>{workerId.replace(/Agent$/, "")}</strong><small>{node?.dependency_worker_ids.length ? `${node.dependency_worker_ids.length} deps` : "root"}</small>
                </span>
              );
            })}
          </div>
          <p>barriers {executionPlan.dependency_barrier_count} · execution order sealed</p>
        </section>
      ) : null}

      {council ? (
        <section className="agent-kernel-council">
          <header><span><BrainCircuit size={12} /> COUNCIL ARBITRATION</span><StatusBadge tone={council.policy_directive === "FAIL_CLOSED" ? "danger" : council.unresolved_hypothesis_count ? "warning" : "success"} compact>{council.policy_directive}</StatusBadge></header>
          <div>
            <span><strong>{council.conflict_count}</strong><small>conflicts</small></span>
            <span><strong>{council.unresolved_hypothesis_count}</strong><small>unresolved</small></span>
            <span><strong>{council.failed_worker_ids.length}</strong><small>failed workers</small></span>
          </div>
          <p>{council.disposition.replaceAll("_", " ")} · root cause {council.root_cause_status}</p>
        </section>
      ) : null}

      {autonomy ? (
        <section className="agent-kernel-autonomy">
          <header><span><ShieldCheck size={12} /> AUTONOMY GUARD</span><code>{shortDigest(autonomy.receipt_sha256)}</code></header>
          <div>
            <span><small>planner</small><strong>{autonomy.planner_mode}</strong></span>
            <span><small>allowed effect</small><strong>{autonomy.allowed_model_effect}</strong></span>
            <span><small>model calls</small><strong>{autonomy.model_call_count}</strong></span>
            <span><small>fallback</small><strong>{autonomy.deterministic_fallback_used ? "DETERMINISTIC" : "NONE"}</strong></span>
          </div>
          <p><LockKeyhole size={11} /> selected set only · create finding=false · approve CAPA=false</p>
        </section>
      ) : null}

      {hasExecutionFailure ? (
        <section className="agent-worker-failures">
          <header><TriangleAlert size={14} /> 服务端返回 Worker 失败</header>
          {failedWorkers.map((receipt) => (
            <div key={receipt.invocation_id}>
              <strong>{receipt.worker_role} · {receipt.error_code ?? "WORKER_FAILED"}</strong>
              <small>attempt {receipt.attempt} · retryable={String(receipt.retryable)} · {shortDigest(receipt.receipt_sha256)}</small>
            </div>
          ))}
          {blockingIssues.slice(0, 3).map((issue) => (
            <p key={issue.issue_code}><b>{issue.issue_code}</b> {issue.required_evidence_or_action}</p>
          ))}
          <ActionButton variant="danger" icon={UserCheck} onClick={onRequestChanges}>
            具名请求补证 / 人工处理
          </ActionButton>
          <small>此卡仅在 API 实际返回 FAILED 时出现；前端不提供故障注入按钮。</small>
        </section>
      ) : null}

      <section className="agent-safety-grid">
        <span><Check size={12} /> human_approval_required=true</span>
        <span><LockKeyhole size={12} /> machine_write=false</span>
        <span><ShieldCheck size={12} /> production_release=false</span>
      </section>
      <div className="agent-case-digest">CASE SHA · {shortDigest(incident.case_sha256)}</div>
    </Panel>
  );
}

export function CommandCenterPage() {
  const navigate = useNavigate();
  const {
    activeWorkspace,
    activeProject,
    connection,
    workspaceLoading,
  } = useProduct();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const requestedSourceId = searchParams.get("source")?.trim() ?? "";
  const requestedCreate = searchParams.get("create") === "1";
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [scopeLoadedRevision, setScopeLoadedRevision] = useState(0);
  const [loadedDetail, setDetail] = useState<AgentTaskDetail>();
  const detail = loadedDetail?.task.task_id === selectedTaskId ? loadedDetail : undefined;
  const [runtimeCapabilities, setRuntimeCapabilities] = useState<AgentRuntimeCapabilities>();
  const [inboxLoading, setInboxLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [scopeError, setScopeError] = useState<string>();
  const [filter, setFilter] = useState<InboxFilter>("ALL");
  const [createOpen, setCreateOpen] = useState(false);
  const [gateAction, setGateAction] = useState<AgentInterventionAction>();
  const [reverificationOpen, setReverificationOpen] = useState(false);
  const [reverificationLoading, setReverificationLoading] = useState(false);
  const [reverificationError, setReverificationError] = useState<string>();
  const [hostedSubmitOpen, setHostedSubmitOpen] = useState(false);
  const [hostedSubmitting, setHostedSubmitting] = useState(false);
  const [hostedSubmitError, setHostedSubmitError] = useState<string>();
  const [hostedReceiptState, setHostedReceiptState] = useState<{
    taskId: string;
    receipt: HostedAgentTeamsReceipt;
  }>();
  const [mutationLoading, setMutationLoading] = useState(false);
  const [mutationError, setMutationError] = useState<string>();
  const [feedback, setFeedback] = useState<InlineFeedback>();
  const scopeGenerationRef = useRef(0);
  const detailGenerationRef = useRef(0);
  const createDeepLinkRef = useRef("");

  const selectTask = useCallback((taskId: string, replace = false) => {
    if (taskId !== selectedTaskId) {
      detailGenerationRef.current += 1;
      setDetail(undefined);
      setDetailLoading(Boolean(taskId));
      setGateAction(undefined);
      setReverificationOpen(false);
      setReverificationError(undefined);
      setHostedSubmitOpen(false);
      setHostedSubmitting(false);
      setHostedSubmitError(undefined);
      setHostedReceiptState(undefined);
      setMutationError(undefined);
      setSelectedTaskId(taskId);
    }
    if (taskId !== requestedTaskId) {
      const next = new URLSearchParams(searchParams);
      if (taskId) next.set("task", taskId);
      else next.delete("task");
      next.delete("source");
      next.delete("create");
      setSearchParams(next, { replace });
    }
  }, [requestedTaskId, searchParams, selectedTaskId, setSearchParams]);

  const loadScope = useCallback(async (showLoading = true, preferredTaskId = "") => {
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    const generation = ++scopeGenerationRef.current;
    detailGenerationRef.current += 1;
    if (!workspaceId || !projectId || connection.api !== "CONNECTED") {
      setTasks([]);
      setSelectedTaskId("");
      setDetail(undefined);
      if (connection.api === "CONNECTED") setRuntimeCapabilities(undefined);
      return;
    }
    if (showLoading) setInboxLoading(true);
    setScopeError(undefined);
    const [taskResult, capabilityResult] = await Promise.allSettled([
      listAgentTasks(workspaceId, projectId),
      getAgentRuntimeCapabilities(),
    ]);
    if (generation !== scopeGenerationRef.current) return;
    if (taskResult.status === "rejected") {
      setTasks([]);
      setSelectedTaskId("");
      setScopeError(readableError(taskResult.reason));
    } else {
      const nextTasks = taskResult.value;
      setTasks(nextTasks);
      const stored = window.sessionStorage.getItem(`visiondata:agent-task:${projectId}`) ?? "";
      const preferred = preferredTaskId || requestedTaskId;
      const requested = nextTasks.find((task) => task.task_id === preferred);
      if (preferred && !requested) {
        setScopeError("深链接 Task 不属于当前 workspace / project，已拒绝定位。");
      }
      setSelectedTaskId((current) => {
        const next = preferred
          ? (requested?.task_id ?? "")
          : (
              nextTasks.find((task) => task.task_id === current)?.task_id ??
              nextTasks.find((task) => task.task_id === stored)?.task_id ??
              nextTasks[0]?.task_id ??
              ""
            );
        if (next) window.sessionStorage.setItem(`visiondata:agent-task:${projectId}`, next);
        return next;
      });
      setScopeLoadedRevision((value) => value + 1);
    }
    if (capabilityResult.status === "fulfilled") {
      setRuntimeCapabilities(capabilityResult.value);
    }
    if (showLoading) setInboxLoading(false);
  }, [activeProject?.project_id, activeWorkspace?.workspace_id, connection.api, requestedTaskId]);

  const loadTaskDetail = useCallback(async (taskId: string, showLoading = true) => {
    if (!taskId || !activeProject || !activeWorkspace) return;
    const scopeGeneration = scopeGenerationRef.current;
    const detailGeneration = ++detailGenerationRef.current;
    if (showLoading) setDetailLoading(true);
    const results = await Promise.allSettled([
      getAgentTask(taskId),
      getAgentTaskPlan(taskId),
      getAgentTaskPreflight(taskId),
      listAgentTaskEvents(taskId),
      listAgentInterventions(taskId),
      listIndustrialIncidentV5(taskId),
      getGoal3HandoffReceipt(taskId),
    ]);
    if (
      scopeGeneration !== scopeGenerationRef.current ||
      detailGeneration !== detailGenerationRef.current
    ) return;
    const taskResult = results[0];
    if (taskResult.status === "rejected") {
      setDetail(undefined);
      setScopeError(readableError(taskResult.reason));
      if (showLoading) setDetailLoading(false);
      return;
    }
    const task = taskResult.value;
    if (
      task.project_id !== activeProject.project_id ||
      task.workspace_id !== activeWorkspace.workspace_id ||
      task.task_id !== taskId
    ) {
      setScopeError("任务响应与当前 workspace / project 绑定不一致，已拒绝显示。");
      setDetail(undefined);
      if (showLoading) setDetailLoading(false);
      return;
    }
    const unavailable: string[] = [];
    const readResult = <T,>(result: PromiseSettledResult<T>, label: string): T | undefined => {
      if (result.status === "fulfilled") return result.value;
      unavailable.push(`${label}: ${readableError(result.reason)}`);
      return undefined;
    };
    const plan = readResult(results[1], "Plan");
    const preflight = readResult(results[2], "Preflight");
    const events = readResult(results[3], "Events") ?? [];
    const interventions = readResult(results[4], "Interventions") ?? [];
    const incidents = readResult(results[5], "Incident v5/v6") ?? [];
    let goal3Handoff = readResult(results[6], "Goal3 handoff");
    const latestIncident = incidents.at(-1);
    if (
      goal3Handoff &&
      (
        goal3Handoff.workspace_id !== task.workspace_id ||
        goal3Handoff.project_id !== task.project_id ||
        goal3Handoff.task_request_sha256 !== task.request_sha256 ||
        goal3Handoff.incident_count !== incidents.length ||
        (latestIncident
          ? (
              goal3Handoff.latest_case_id !== latestIncident.case_id ||
              goal3Handoff.latest_case_sha256 !== latestIncident.case_sha256 ||
              goal3Handoff.latest_case_version !== latestIncident.case_version
            )
          : goal3Handoff.latest_case_id !== null)
      )
    ) {
      goal3Handoff = undefined;
      unavailable.push("Goal3 handoff: 回执与当前 Task / workspace / project / Incident head 绑定不一致");
    }
    let governedContext: GovernedIncidentContext | undefined;
    if (latestIncident?.governed_memory_retrieval_receipt_sha256) {
      try {
        governedContext = await getIndustrialIncidentGovernedContext(
          taskId,
          latestIncident.case_id,
          latestIncident.case_sha256,
        );
        if (
          governedContext.retrieval_receipt.receipt_sha256 !==
            latestIncident.governed_memory_retrieval_receipt_sha256 ||
          (latestIncident.governed_memory_planning_input_sha256 &&
            governedContext.planning_input?.input_sha256 !==
              latestIncident.governed_memory_planning_input_sha256)
        ) {
          governedContext = undefined;
          unavailable.push("Governed memory: Case 与检索 / Planning Input 回执摘要不一致");
        }
      } catch (caught) {
        unavailable.push(`Governed memory: ${readableError(caught)}`);
      }
    }
    let releaseReadiness: AgentReleaseReadiness | undefined;
    if (task.execution_status === "COMPLETED") {
      try {
        releaseReadiness = await getAgentReleaseReadiness(taskId);
      } catch (caught) {
        unavailable.push(`Release readiness: ${readableError(caught)}`);
      }
    }
    if (
      scopeGeneration !== scopeGenerationRef.current ||
      detailGeneration !== detailGenerationRef.current
    ) return;
    setDetail({ task, plan, preflight, events, interventions, incidents, releaseReadiness, goal3Handoff, governedContext, unavailable });
    setTasks((current) => current.map((item) => item.task_id === task.task_id ? task : item));
    if (showLoading) setDetailLoading(false);
  }, [activeProject, activeWorkspace]);

  useEffect(() => {
    setDetail(undefined);
    setSelectedTaskId("");
    setHostedSubmitOpen(false);
    setHostedSubmitting(false);
    setHostedSubmitError(undefined);
    setHostedReceiptState(undefined);
    void loadScope();
  }, [loadScope]);

  useEffect(() => {
    if (!requestedCreate || !requestedSourceId || !activeProject || !activeWorkspace) return;
    const deepLinkKey = `${activeWorkspace.workspace_id}:${activeProject.project_id}:${requestedSourceId}`;
    if (createDeepLinkRef.current === deepLinkKey) return;
    createDeepLinkRef.current = deepLinkKey;
    setCreateOpen(true);
  }, [activeProject, activeWorkspace, requestedCreate, requestedSourceId]);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(undefined);
      setDetailLoading(false);
      return;
    }
    if (activeProject) {
      window.sessionStorage.setItem(
        `visiondata:agent-task:${activeProject.project_id}`,
        selectedTaskId,
      );
    }
    void loadTaskDetail(selectedTaskId);
  }, [activeProject?.project_id, loadTaskDetail, scopeLoadedRevision, selectedTaskId]);

  useEffect(() => {
    if (
      !detail ||
      detail.task.task_id !== selectedTaskId ||
      !["CREATED", "RUNNING", "VERIFYING"].includes(detail.task.execution_status)
    ) {
      return;
    }
    let disposed = false;
    let timeout: number | undefined;
    const poll = async () => {
      await loadTaskDetail(selectedTaskId, false);
      if (!disposed) timeout = window.setTimeout(() => void poll(), 2_400);
    };
    timeout = window.setTimeout(() => void poll(), 2_400);
    return () => {
      disposed = true;
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [detail?.task.execution_status, detail?.task.task_id, loadTaskDetail, selectedTaskId]);

  useEffect(() => {
    if (!feedback) return;
    const timeout = window.setTimeout(() => setFeedback(undefined), 4_500);
    return () => window.clearTimeout(timeout);
  }, [feedback]);

  const filteredTasks = useMemo(() => tasks.filter((task) => {
    if (filter === "HUMAN") {
      return task.execution_status === "PLANNED" || task.execution_status === "COMPLETED" || task.execution_status === "FAILED";
    }
    if (filter === "RUNNING") return ["CREATED", "RUNNING", "VERIFYING"].includes(task.execution_status);
    if (filter === "DONE") return ["COMPLETED", "CANCELLED", "ARCHIVED"].includes(task.execution_status);
    return true;
  }), [filter, tasks]);

  const handleCreated = (task: AgentTask) => {
    if (task.project_id !== activeProject?.project_id) return;
    setCreateOpen(false);
    setTasks((current) => [task, ...current.filter((item) => item.task_id !== task.task_id)]);
    selectTask(task.task_id);
    setFeedback({ tone: "success", message: "任务已写入真实任务账本，正在读取 Plan 与 Preflight。" });
  };

  const submitIntervention = async (actorName: string, note: string) => {
    if (!gateAction || !detail || detail.task.task_id !== selectedTaskId || mutationLoading) return;
    const taskId = detail.task.task_id;
    const scopeGeneration = scopeGenerationRef.current;
    const detailGeneration = detailGenerationRef.current;
    setMutationLoading(true);
    setMutationError(undefined);
    try {
      await createAgentIntervention(
        taskId,
        gateAction,
        `[具名复核人 ${actorName}; account=${operatorActorUserId}] ${note}`,
      );
      if (
        scopeGeneration !== scopeGenerationRef.current ||
        detailGeneration !== detailGenerationRef.current
      ) return;
      const label = interventionLabels[gateAction];
      setGateAction(undefined);
      setFeedback({ tone: "success", message: `${label}已写入 append-only intervention 账本。` });
      await loadScope(false);
      await loadTaskDetail(taskId, false);
      window.setTimeout(() => void loadTaskDetail(taskId, false), 850);
    } catch (caught) {
      if (scopeGeneration === scopeGenerationRef.current) setMutationError(readableError(caught));
    } finally {
      if (scopeGeneration === scopeGenerationRef.current) setMutationLoading(false);
    }
  };

  const submitReverification = async (note: string, idempotencyKey: string) => {
    if (!detail || detail.task.task_id !== selectedTaskId || reverificationLoading) return;
    const parentTaskId = detail.task.task_id;
    const scopeGeneration = scopeGenerationRef.current;
    setReverificationLoading(true);
    setReverificationError(undefined);
    try {
      const child = await createAgentReverification({
        taskId: parentTaskId,
        note: `[operator=${operatorActorUserId}] ${note}`,
        sourceId: detail.task.source_id ?? undefined,
        idempotencyKey,
      });
      if (scopeGeneration !== scopeGenerationRef.current) return;
      setReverificationOpen(false);
      setTasks((current) => [child, ...current.filter((item) => item.task_id !== child.task_id)]);
      selectTask(child.task_id);
      setFeedback({
        tone: "success",
        message: `Child Run ${child.task_id} 已建立；Parent 证据保持不可变，等待具名 Plan 审批。`,
      });
      await loadScope(false, child.task_id);
      await loadTaskDetail(child.task_id, false);
    } catch (caught) {
      if (scopeGeneration === scopeGenerationRef.current) {
        setReverificationError(readableError(caught));
      }
    } finally {
      if (scopeGeneration === scopeGenerationRef.current) {
        setReverificationLoading(false);
      }
    }
  };

  const submitHostedTask = async (approvalId: string) => {
    if (!detail || detail.task.task_id !== selectedTaskId || hostedSubmitting) return;
    const taskId = detail.task.task_id;
    const scopeGeneration = scopeGenerationRef.current;
    const detailGeneration = detailGenerationRef.current;
    setHostedSubmitting(true);
    setHostedSubmitError(undefined);
    setHostedReceiptState(undefined);
    try {
      const receipt = await submitHostedAgentTeamsTask({ taskId, approvalId });
      if (
        scopeGeneration !== scopeGenerationRef.current ||
        detailGeneration !== detailGenerationRef.current ||
        selectedTaskId !== taskId
      ) return;
      setHostedSubmitOpen(false);
      setHostedReceiptState({ taskId, receipt });
      setFeedback({
        tone: receipt.status === "PASS" ? "success" : "info",
        message: `Hosted 回执已验收：${receipt.operation_status}；hosted_runtime_verified=false。`,
      });
    } catch (caught) {
      if (
        scopeGeneration === scopeGenerationRef.current &&
        detailGeneration === detailGenerationRef.current
      ) {
        setHostedSubmitError(readableError(caught));
      }
    } finally {
      if (scopeGeneration === scopeGenerationRef.current) setHostedSubmitting(false);
    }
  };

  const resultIntervened = detail?.interventions.some(
    (item) => item.action === "acknowledge_result" || item.action === "request_changes",
  ) ?? false;
  const detailMatchesSelection = detail?.task.task_id === selectedTaskId;
  const latestIncident = detail?.incidents.at(-1);
  const incidentUnavailableReason = detail?.unavailable.find(
    (item) => item.startsWith("Incident v5/v6:"),
  );
  const governedMemoryUnavailableReason = detail?.unavailable.find(
    (item) => item.startsWith("Governed memory:"),
  ) ?? incidentUnavailableReason;
  const goal3HandoffUnavailableReason = detail?.unavailable.find(
    (item) => item.startsWith("Goal3 handoff:"),
  ) ?? incidentUnavailableReason;
  const preflightBlocked = detail?.preflight?.prerequisite_ready === false;
  const preflightConsumed = detail
    ? ["RUNNING", "VERIFYING", "COMPLETED"].includes(detail.task.execution_status)
    : false;
  const planApproval = detail?.interventions.find((item) => item.action === "approve_plan");
  const planCancellation = detail?.interventions.find((item) => item.action === "cancel_plan");
  const preflightCancelled = detail?.task.execution_status === "CANCELLED";
  const hostedReceipt = hostedReceiptState?.taskId === selectedTaskId
    ? hostedReceiptState.receipt
    : undefined;

  if (workspaceLoading) {
    return <div className="agent-page-loading"><LoaderCircle className="is-spinning" /> 正在读取工作范围…</div>;
  }

  if (connection.api !== "CONNECTED") {
    return (
      <div className="agent-page agent-page--empty">
        <EmptyState icon={LockKeyhole} title="本地 API 未连接" description="任务工作台只显示真实任务账本，不会退回 fixture dashboard。请先启动本地 API。" />
      </div>
    );
  }

  if (!activeWorkspace || !activeProject) {
    return (
      <div className="agent-page agent-page--empty">
        <EmptyState icon={Inbox} title="请选择或创建项目" description="Agent Task 必须绑定 active workspace / project。系统不会自动生成任务或填充演示结果。" />
      </div>
    );
  }

  return (
    <div className="agent-page">
      <header className="agent-page__toolbar">
        <div>
          <span>AGENT TASK WORKBENCH</span>
          <strong>{activeProject.name}</strong>
          <small>问题 → 确定性工具 → 人工闸门 → 可审计反馈</small>
        </div>
        <div className="agent-page__toolbar-actions">
          <StatusBadge tone="success" compact>LIVE LOCAL API</StatusBadge>
          {activeProject.source_kind === "synthetic_demo" ? <StatusBadge tone="info" compact>SAMPLE SCOPE</StatusBadge> : null}
          <button
            type="button"
            onClick={() => {
              const currentTaskId = selectedTaskId;
              void loadScope(true, currentTaskId).then(() => {
                if (currentTaskId) void loadTaskDetail(currentTaskId, false);
              });
            }}
            disabled={inboxLoading}
            title="刷新当前项目"
          >
            <RefreshCw className={inboxLoading ? "is-spinning" : ""} size={14} />
          </button>
          <ActionButton icon={Plus} onClick={() => setCreateOpen(true)}>新建任务</ActionButton>
        </div>
      </header>

      {feedback ? (
        <div className={`agent-feedback is-${feedback.tone}`} role="status">
          {feedback.tone === "success" ? <CheckCircle2 size={15} /> : feedback.tone === "danger" ? <TriangleAlert size={15} /> : <Activity size={15} />}
          {feedback.message}
        </div>
      ) : null}
      {scopeError ? <div className="agent-feedback is-danger" role="alert"><TriangleAlert size={15} />{scopeError}</div> : null}

      <div className="agent-workbench">
        <Panel className="agent-inbox" variant="subtle">
          <header className="agent-column-header">
            <div><Inbox size={14} /><strong>Task Inbox</strong></div>
            <span>{tasks.length}</span>
          </header>
          <div className="agent-inbox-filters">
            {([
              ["ALL", "全部"],
              ["HUMAN", "待人工"],
              ["RUNNING", "运行中"],
              ["DONE", "已完成"],
            ] as const).map(([value, label]) => (
              <button type="button" className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)} key={value}>{label}</button>
            ))}
          </div>
          <div className="agent-inbox-list">
            {inboxLoading && tasks.length === 0 ? (
              <div className="agent-list-loading"><LoaderCircle className="is-spinning" /> 正在读取任务账本</div>
            ) : filteredTasks.length === 0 ? (
              <div className="agent-inbox-empty">
                <Inbox size={18} />
                <strong>{tasks.length === 0 ? "当前项目还没有任务" : "该切片没有任务"}</strong>
                <p>{tasks.length === 0 ? "从一个真实、明确的问题开始；不会自动造数据。" : "切换上方状态筛选。"}</p>
                {tasks.length === 0 ? <button type="button" onClick={() => setCreateOpen(true)}><Plus size={13} /> 创建第一个任务</button> : null}
              </div>
            ) : filteredTasks.map((task) => (
              <button
                type="button"
                className={selectedTaskId === task.task_id ? "is-active" : ""}
                onClick={() => selectTask(task.task_id)}
                key={task.task_id}
              >
                <span className={`agent-task-state is-${taskTone(task)}`} />
                <div>
                  <strong>{task.goal}</strong>
                  <small>{task.current_phase} · {formatTime(task.updated_at)}</small>
                  <span><StatusBadge tone={taskTone(task)} compact>{task.execution_status}</StatusBadge>{task.plan_approval_required ? <em>HITL</em> : null}</span>
                </div>
                <ChevronRight size={13} />
              </button>
            ))}
          </div>
          <footer>
            <ShieldCheck size={12} /> scope: {activeWorkspace.workspace_id} / {activeProject.project_id}
          </footer>
        </Panel>

        <main className="agent-task-canvas">
          {!selectedTaskId ? (
            <div className="agent-task-empty agent-task-empty--launchpad">
              <div className="agent-empty-launchpad__mark"><ListChecks size={25} /></div>
              <span className="agent-empty-launchpad__kicker">CONTROLLED AGENT ENTRY</span>
              <strong>从一个可验收的问题开始</strong>
              <p>定义目标与工具边界后，系统才会生成 Plan、执行 Preflight，并把需要判断的动作停在人工闸门前。</p>
              <button type="button" onClick={() => setCreateOpen(true)}><Plus size={14} /> 新建受控任务</button>
              <div className="agent-empty-launchpad__flow" aria-label="受控 Agent 任务流程">
                <span><i>01</i><FileCheck2 size={15} /><strong>任务合同</strong><small>目标与来源绑定</small></span>
                <span><i>02</i><Wrench size={15} /><strong>确定性执行</strong><small>工具回执可追溯</small></span>
                <span><i>03</i><UserCheck size={15} /><strong>人工闸门</strong><small>高风险动作不越权</small></span>
              </div>
              <small className="agent-empty-launchpad__boundary"><ShieldCheck size={12} /> 没有真实任务，就不显示伪造的 Agent 成果。</small>
            </div>
          ) : detailLoading && !detailMatchesSelection ? (
            <div className="agent-task-empty"><LoaderCircle className="is-spinning" size={23} /><strong>正在读取任务合同与活动账本…</strong></div>
          ) : detail && detailMatchesSelection ? (
            <>
              <header className="agent-task-header" id="task-contract">
                <div>
                  <span>TASK / {detail.task.task_id}</span>
                  <h1>{detail.task.goal}</h1>
                  <p>{detail.task.scenario_profile} · {detail.task.source_kind} · created by {detail.task.created_by}</p>
                  {detail.plan?.source_binding_sha256 ? (
                    <p>source {detail.plan.source_id} · binding {shortDigest(detail.plan.source_binding_sha256)}</p>
                  ) : null}
                </div>
                <StatusBadge tone={taskTone(detail.task)}>{detail.task.execution_status}</StatusBadge>
              </header>
              <TaskLifecycle task={detail.task} />
              <TaskCapabilityStrip detail={detail} />

              {detail.task.execution_status === "FAILED" ? (
                <section className="agent-task-failure">
                  <TriangleAlert size={18} />
                  <div><strong>{detail.task.error_code ?? "TASK_FAILED"}</strong><p>{detail.task.error_message ?? "任务失败，未生成可采信的成功结果。"}</p></div>
                  <ActionButton variant="danger" onClick={() => setGateAction("request_changes")}>具名请求处理</ActionButton>
                </section>
              ) : null}

              <section className="agent-task-section" id="task-preflight">
                <header>
                  <div><FileCheck2 size={14} /><span>{preflightConsumed ? "Preflight / 已消费的运行前门禁" : preflightCancelled ? "Preflight / 已取消的运行计划" : "Preflight / 运行前置条件"}</span></div>
                  {preflightCancelled ? (
                    <StatusBadge tone="locked" compact>CANCELLED_BEFORE_RUN</StatusBadge>
                  ) : preflightConsumed ? (
                    <StatusBadge tone="success" compact>{detail.task.execution_status === "COMPLETED" ? "CONSUMED_AND_COMPLETED" : "CONSUMED"}</StatusBadge>
                  ) : detail.preflight ? (
                    <StatusBadge tone={detail.preflight.prerequisite_ready ? "success" : "danger"} compact>{detail.preflight.overall_status}</StatusBadge>
                  ) : null}
                </header>
                {preflightCancelled ? (
                  <div className="agent-preflight-grid">
                    <article className="is-pending">
                      <XCircle size={14} />
                      <div>
                        <strong>计划已在工具执行前具名取消</strong>
                        <p>
                          当前 Task 不会再接受批准或启动；没有运行事件，也没有伪造执行证据。
                          如需重新处理，应创建新的受控 Task。
                        </p>
                        <small>
                          {planCancellation
                            ? `cancellation:${shortDigest(planCancellation.before_snapshot_sha256)}`
                            : "task-interventions:append-only"}
                        </small>
                      </div>
                      <StatusBadge tone="locked" compact>CANCELLED</StatusBadge>
                    </article>
                  </div>
                ) : preflightConsumed ? (
                  <div className="agent-preflight-grid">
                    <article className="is-pass">
                      <CheckCircle2 size={14} />
                      <div>
                        <strong>运行前门禁已被本次执行消费</strong>
                        <p>
                          Task 已离开 PLANNED；此时 live Preflight 的 NOT_RUNNABLE 只表示不可原地重复执行，
                          不表示本次批准失败。复验必须创建同合同 Child Run。
                        </p>
                        <small>
                          {planApproval?.approval_binding
                            ? `approval-binding:${shortDigest(planApproval.approval_binding.binding_sha256)}`
                            : `task-plan:${shortDigest(detail.plan?.plan_sha256)} · approval_not_required`}
                        </small>
                      </div>
                      <StatusBadge tone="success" compact>SEALED</StatusBadge>
                    </article>
                  </div>
                ) : detail.preflight ? (
                  <div className="agent-preflight-grid">
                    {detail.preflight.checks.map((check) => (
                      <article className={`is-${check.status.toLowerCase()}`} key={check.key}>
                        {check.status === "PASS" ? <CheckCircle2 size={14} /> : check.status === "BLOCKED" ? <XCircle size={14} /> : <Clock3 size={14} />}
                        <div><strong>{check.label}</strong><p>{check.summary}</p><small>{check.evidence_ref}{check.evidence_sha256 ? ` · ${shortDigest(check.evidence_sha256)}` : ""}</small></div>
                        <StatusBadge tone={checkTone(check.status)} compact>{check.status}</StatusBadge>
                      </article>
                    ))}
                  </div>
                ) : <div className="agent-section-unavailable">Preflight 当前不可读取，不能据此宣称 READY。</div>}
              </section>

              <section className="agent-task-section" id="task-plan">
                <header>
                  <div><Sparkles size={14} /><span>Plan / 可批准执行计划</span></div>
                  {detail.plan ? <code>{shortDigest(detail.plan.plan_sha256)}</code> : null}
                </header>
                {detail.plan ? (
                  <div className="agent-plan-list">
                    {detail.plan.steps.map((step, index) => (
                      <article key={step.step_id}>
                        <span>{index + 1}</span>
                        <div><small>{step.phase} · {step.agent_role}</small><strong>{step.objective}</strong><p>{step.tool_names.map((tool) => toolLabels[tool] ?? tool).join(" · ") || "无工具调用"}</p></div>
                        {step.human_gate ? <StatusBadge tone="warning" compact>HUMAN GATE</StatusBadge> : null}
                      </article>
                    ))}
                    <footer>
                      <LockKeyhole size={12} /> production authority = {detail.plan.production_authority} · {detail.plan.dynamic_replanning_policy}
                      {detail.plan.source_binding_sha256 ? <> · source binding {shortDigest(detail.plan.source_binding_sha256)}</> : null}
                    </footer>
                  </div>
                ) : <div className="agent-section-unavailable">Plan 当前不可读取，人工批准保持不可用。</div>}
              </section>

              <section className="agent-task-section" id="task-activity">
                <header>
                  <div><Activity size={14} /><span>Agent Activity / 可审计活动</span></div>
                  <small>不显示私有思维链</small>
                </header>
                {detail.events.length > 0 ? (
                  <div className="agent-activity-list">
                    {detail.events.map((event) => (
                      <article key={`${event.task_id}-${event.sequence}`}>
                        <span>{event.sequence}</span>
                        <div><small>{event.phase} / {event.stage}</small><strong>{event.summary}</strong><p>{event.status} · {formatTime(event.created_at)}</p></div>
                        <StatusBadge tone={event.status.includes("FAIL") ? "danger" : event.status.includes("COMP") || event.status.includes("PASS") ? "success" : "info"} compact>{event.status}</StatusBadge>
                      </article>
                    ))}
                  </div>
                ) : <div className="agent-section-unavailable">尚无运行事件。PLANNED 任务须先通过人工审批。</div>}
              </section>

              {detail.releaseReadiness ? (
                <section className="agent-task-section agent-release-readiness" id="task-result">
                  <header><div><ShieldCheck size={14} /><span>Result / Release Readiness</span></div><StatusBadge tone={detail.releaseReadiness.overall_status === "READY_FOR_HUMAN_REVIEW" ? "success" : "warning"} compact>{detail.releaseReadiness.overall_status}</StatusBadge></header>
                  <div><strong>{detail.releaseReadiness.final_gate_decision}</strong><p>{detail.releaseReadiness.required_human_action}</p><small>evidence {shortDigest(detail.releaseReadiness.evidence_sha256)} · integrity {detail.releaseReadiness.evidence_integrity} · production_release_allowed=false</small></div>
                </section>
              ) : null}

              {detail.unavailable.length > 0 ? (
                <details className="agent-partial-errors">
                  <summary>部分只读视图不可用 · {detail.unavailable.length}</summary>
                  {detail.unavailable.map((item) => <p key={item}>{item}</p>)}
                </details>
              ) : null}
              <div className="agent-identity-boundary">
                {detail.plan?.source_binding_sha256 ? <ShieldCheck size={14} /> : <AlertCircle size={14} />}
                {detail.plan?.source_binding_sha256
                  ? `Task 已绑定服务端核验的不可变来源摘要 ${detail.plan.source_binding_sha256}。`
                  : "当前 Task 没有工作簿快照绑定；不得把页面中的图片自动视为该任务输入。"}
              </div>
            </>
          ) : (
            <div className="agent-task-empty"><TriangleAlert size={22} /><strong>任务详情不可读取</strong><p>请刷新当前项目；前端不会用 fixture 补位。</p></div>
          )}
        </main>

        <aside className="agent-side-rail">
          <Panel id="task-human-gate" className="agent-side-card" variant="subtle">
            <header className="agent-side-card__header">
              <span><UserCheck size={14} /> HUMAN GATE</span>
              <StatusBadge tone="warning" compact>HUMAN ONLY</StatusBadge>
            </header>
            {!detail ? (
              <div className="agent-side-empty"><CircleDot size={18} /><p>选择任务后显示可执行人工动作。</p></div>
            ) : (
              <>
                <div className="agent-authority-rules">
                  <span><Check size={12} /> Agent 可理解、规划、调用只读工具</span>
                  <span><LockKeyhole size={12} /> 无生产放行与设备写入按钮</span>
                  <span><ShieldCheck size={12} /> 所有人工动作写入不可变账本</span>
                </div>
                {detail.task.execution_status === "PLANNED" && detail.task.plan_approval_required ? (
                  <div className="agent-gate-action">
                    <strong>Plan 等待具名审批</strong>
                    <p>{preflightBlocked ? "Preflight 有阻断项，必须先处理。" : "核对 Plan、来源、工具权限与安全边界后再启动。"}</p>
                    <div>
                      <ActionButton icon={UserCheck} disabled={preflightBlocked || !detail.plan} onClick={() => setGateAction("approve_plan")}>审批并启动</ActionButton>
                      <ActionButton variant="danger" icon={XCircle} onClick={() => setGateAction("cancel_plan")}>取消计划</ActionButton>
                    </div>
                  </div>
                ) : null}
                {detail.task.execution_status === "COMPLETED" && !resultIntervened ? (
                  <div className="agent-gate-action">
                    <strong>结果等待人工反馈</strong>
                    <p>确认已审阅，或记录具体补证要求。两者都不会授予生产权限。</p>
                    <div><ActionButton icon={CheckCircle2} onClick={() => setGateAction("acknowledge_result")}>确认已审阅</ActionButton><ActionButton variant="danger" icon={TriangleAlert} onClick={() => setGateAction("request_changes")}>请求补证</ActionButton></div>
                  </div>
                ) : null}
                {detail.task.execution_status === "COMPLETED" ? (
                  <div className="agent-gate-action">
                    <strong>需要验证整改结果？</strong>
                    <p>创建同合同 Child Run；Parent 的 GateResult 与 Evidence ZIP 保持不可变。</p>
                    <ActionButton icon={RefreshCw} onClick={() => { setReverificationError(undefined); setReverificationOpen(true); }}>创建复验 Child Run</ActionButton>
                  </div>
                ) : null}
                {["RUNNING", "VERIFYING", "CREATED"].includes(detail.task.execution_status) ? (
                  <div className="agent-gate-wait"><LoaderCircle className="is-spinning" size={15} /><span><strong>Agent 正在办事</strong><small>页面按真实 Task/Event 账本轮询；工具失败会转为失败卡，不播放假动画。</small></span></div>
                ) : null}
                {detail.interventions.length > 0 ? (
                  <div className="agent-intervention-ledger">
                    <header>IMMUTABLE INTERVENTIONS</header>
                    {detail.interventions.map((item) => (
                      <article key={item.intervention_id}>
                        <span>{item.sequence}</span>
                        <div><strong>{interventionLabels[item.action]}</strong><p>{item.note}</p><small>{item.actor_user_id} · {formatTime(item.created_at)} · {shortDigest(item.before_snapshot_sha256)}</small></div>
                      </article>
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </Panel>

          <Panel className="agent-side-card hosted-task-transport" variant="subtle">
            <header className="agent-side-card__header">
              <span><RadioTower size={14} /> HOSTED TRANSPORT</span>
              <StatusBadge tone={hostedReceipt?.status === "PASS" ? "success" : hostedReceipt ? "warning" : "locked"} compact>
                {hostedReceipt?.operation_status ?? "NOT SUBMITTED"}
              </StatusBadge>
            </header>
            {!detail ? (
              <div className="agent-side-empty"><RadioTower size={18} /><p>选择 Task 后才能打开具名远程提交闸门。</p></div>
            ) : (
              <>
                <div className="hosted-task-transport__boundary">
                  <ShieldCheck size={14} />
                  <span><strong>页面不会自动探测或提交</strong><small>远程写操作必须输入 approval_id 并再次人工确认。</small></span>
                </div>
                {hostedReceipt ? (
                  <article className="hosted-task-receipt">
                    <div><span>operation</span><strong>{hostedReceipt.operation}</strong></div>
                    <div><span>approval</span><strong>{hostedReceipt.approval_id}</strong></div>
                    <div><span>wait</span><strong>{String(hostedReceipt.wait_for_remote_execution)}</strong></div>
                    <div><span>hosted verified</span><strong>{String(hostedReceipt.hosted_runtime_verified)}</strong></div>
                    <code>{hostedReceipt.receipt_sha256}</code>
                    <p>{hostedReceipt.boundary}</p>
                  </article>
                ) : (
                  <p className="hosted-task-transport__empty">当前 Task 没有 Hosted submission receipt；本地完成不等于托管执行已发生。</p>
                )}
                <ActionButton
                  icon={Send}
                  disabled={hostedSubmitting}
                  onClick={() => {
                    setHostedSubmitError(undefined);
                    setHostedSubmitOpen(true);
                  }}
                >
                  {hostedReceipt ? "发起新的具名提交" : "打开远程提交闸门"}
                </ActionButton>
              </>
            )}
          </Panel>

          <Goal2MemoryCard incident={latestIncident} context={detail?.governedContext} capabilities={runtimeCapabilities} unavailableReason={governedMemoryUnavailableReason} />

          <IncidentGoal3Card
            incident={latestIncident}
            handoff={detail?.goal3Handoff}
            unavailableReason={goal3HandoffUnavailableReason}
            onOpenIntake={() => {
              if (!detail) return;
              navigate(`/cases?task=${encodeURIComponent(detail.task.task_id)}&import=1`);
            }}
            onOpenIncident={() => {
              if (!detail || !latestIncident) return;
              navigate(`/cases/${encodeURIComponent(latestIncident.case_id)}?task=${encodeURIComponent(detail.task.task_id)}`);
            }}
            onRequestChanges={() => setGateAction("request_changes")}
          />

          <Panel className="agent-side-card agent-runtime-card" variant="subtle">
            <header className="agent-side-card__header"><span><Activity size={14} /> RUNTIME SAFETY</span><StatusBadge tone="success" compact>SECRET FREE</StatusBadge></header>
            {runtimeCapabilities ? (
              <>
                {runtimeCapabilities.model_profiles.map((profile) => (
                  <div className="agent-runtime-profile" key={profile.profile_id}>
                    <span className={`runtime-dot runtime-dot--${profile.availability === "AVAILABLE" ? "connected" : "unavailable"}`} />
                    <div><strong>{profile.label}</strong><small>{profile.profile_id} · {profile.supported_modes.join("/")} · {profile.availability}</small></div>
                  </div>
                ))}
                <div className="agent-runtime-policy"><span>authority</span><strong>{runtimeCapabilities.production_decision_authority}</strong><span>server policy</span><code>{shortDigest(runtimeCapabilities.server_policy_sha256)}</code><span>secrets exposed</span><strong>{String(runtimeCapabilities.secrets_exposed)}</strong></div>
              </>
            ) : <div className="agent-section-unavailable">Runtime capabilities 暂不可读取。</div>}
          </Panel>
        </aside>
      </div>

      {createOpen ? <TaskCreationDialog workspace={activeWorkspace} project={activeProject} preferredSourceId={requestedSourceId || undefined} onClose={() => setCreateOpen(false)} onCreated={handleCreated} /> : null}
      {gateAction && detail ? (
        <HumanGateDialog
          action={gateAction}
          task={detail.task}
          submitting={mutationLoading}
          serverError={mutationError}
          onClose={() => { setGateAction(undefined); setMutationError(undefined); }}
          onSubmit={(actorName, note) => void submitIntervention(actorName, note)}
        />
      ) : null}
      {reverificationOpen && detail ? (
        <ReverificationDialog
          task={detail.task}
          submitting={reverificationLoading}
          serverError={reverificationError}
          onClose={() => { setReverificationOpen(false); setReverificationError(undefined); }}
          onSubmit={(note, idempotencyKey) => void submitReverification(note, idempotencyKey)}
        />
      ) : null}
      {hostedSubmitOpen && detail ? (
        <HostedAgentTeamsDialog
          task={detail.task}
          submitting={hostedSubmitting}
          serverError={hostedSubmitError}
          onClose={() => { setHostedSubmitOpen(false); setHostedSubmitError(undefined); }}
          onSubmit={(approvalId) => void submitHostedTask(approvalId)}
        />
      ) : null}
    </div>
  );
}
