import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleOff,
  Download,
  GitBranch,
  LoaderCircle,
  LockKeyhole,
  Network,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Siren,
  UserCheck,
  Wrench,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import type {
  AgentTask,
  IncidentInteractionReceipt,
  IndustrialIncident,
  IndustrialIncidentAuthoritySnapshot,
  IndustrialIncidentCommandReceipt,
  IndustrialIncidentCommandResult,
  IndustrialIncidentDecisionReceipt,
  IndustrialIncidentHumanDecision,
} from "../agentDomain";
import { useProduct } from "../ProductContext";
import {
  OperatorApiError,
  getAgentTask,
  getIndustrialIncident,
  getIndustrialIncidentAuthoritySnapshot,
  getIndustrialIncidentCommand,
  getIndustrialIncidentInteractionReceipt,
  listIndustrialIncidentDecisions,
  listIndustrialIncidents,
  recordIndustrialIncidentDecision,
  resumeIndustrialIncident,
} from "../data/api";
import type { StatusTone } from "../domain";
import {
  ActionButton,
  ClaimBoundary,
  Digest,
  EvidenceSourceBadge,
  Modal,
  Panel,
  PanelHeader,
  StatusBadge,
} from "./ui";
import { TaskVisualEvidencePanel } from "./TaskVisualEvidencePanel";
import { IncidentInteractionTimeline } from "./IncidentInteractionTimeline";
import { IncidentReviewProjectionPanel } from "./IncidentReviewProjectionPanel";

interface LiveIncidentWorkbenchProps {
  taskId: string;
  caseId: string;
}

interface LoadedIncidentScope {
  task: AgentTask;
  incident: IndustrialIncident;
  decisions: IndustrialIncidentDecisionReceipt[];
  relatedCases: IndustrialIncident[];
  interaction?: IncidentInteractionReceipt;
  interactionError?: string;
  authoritySnapshot?: IndustrialIncidentAuthoritySnapshot;
  authorityError?: string;
}

type LoadState = "LOADING" | "READY" | "ERROR" | "NOT_CONNECTED";

type IncidentCommandViewStatus = "COMPLETED" | "REJECTED" | "PENDING";

interface IncidentCommandReconciliation {
  commandId: string;
  status: IncidentCommandViewStatus;
  detail: string;
  receipt?: IndustrialIncidentCommandReceipt;
}

const decisionLabels: Record<IndustrialIncidentHumanDecision, string> = {
  CONTINUE_HOLD: "继续 HOLD，等待补证",
  ESCALATE_INVESTIGATION: "升级人工调查",
  SELECT_REMEDIATION_PLAN: "选择整改方案并建立 CAPA",
  REQUEST_REVERIFICATION: "请求独立复验",
  REJECT_RECOMMENDATION: "拒绝当前 Agent 建议",
};

const incidentRequestSchemas = new Set([
  "visiondata-gate.industrial-incident-request.v1",
  "visiondata-gate.industrial-incident-request.v2",
  "visiondata-gate.industrial-incident-request.v3",
]);

function compact(value: string | null | undefined, head = 10, tail = 6): string {
  if (!value) return "—";
  return value.length > head + tail + 1
    ? `${value.slice(0, head)}…${value.slice(-tail)}`
    : value;
}

function tone(value: string): StatusTone {
  const normalized = value.toUpperCase();
  if (/FAILED|BLOCK|HOLD|REJECT|INCOMPLETE/.test(normalized)) return "danger";
  if (/WAIT|PENDING|RECAPTURE|REVIEW|REQUIRED/.test(normalized)) return "warning";
  if (/PASS|COMPLETE|SUCCEEDED|CURRENT|READY/.test(normalized)) return "success";
  if (/RUNNING|DISPATCH|PLANNED|CREATED/.test(normalized)) return "info";
  return "neutral";
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : "本地工作台请求失败";
}

async function contentIdempotencyKey(prefix: string, value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest), (item) =>
    item.toString(16).padStart(2, "0"),
  ).join("");
  return `${prefix}-${hex.slice(0, 48)}`;
}

async function anticipatedIncidentCommandId(input: {
  taskId: string;
  operation: "RECORD_DECISION" | "RESUME_CASE";
  targetCaseId: string;
  idempotencyKey: string;
}): Promise<string> {
  // Mirrors the server's canonical JSON contract, including its terminal newline.
  const canonical = `${JSON.stringify({
    idempotency_key: input.idempotencyKey,
    operation: input.operation,
    target_case_id: input.targetCaseId,
    task_id: input.taskId,
  })}\n`;
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonical),
  );
  const hex = Array.from(new Uint8Array(digest), (item) =>
    item.toString(16).padStart(2, "0"),
  ).join("");
  return `incident_command_${hex.slice(0, 24)}`;
}

function isUnknownCommandOutcome(value: unknown): value is OperatorApiError {
  return (
    value instanceof OperatorApiError &&
    (value.status === 0 ||
      value.code === "REQUEST_TIMEOUT" ||
      value.code === "NETWORK_UNAVAILABLE" ||
      value.code === "incident_command_uncertain" ||
      Boolean(value.incidentCommandId))
  );
}

function unknownCommandOutcomeDetail(value: OperatorApiError): string {
  const prefix = "WRITE RESULT UNKNOWN / HOLD · ";
  if (value.code === "incident_command_uncertain") {
    return `${prefix}服务端返回 UNCERTAIN：命令已准入但缺少终态回执；禁止盲重试，请显式查询。`;
  }
  if (value.code === "NETWORK_UNAVAILABLE") {
    return `${prefix}连接中断，服务端可能已经接收命令；保留原命令标识并等待显式对账。`;
  }
  return `${prefix}请求超时，执行结果未知；保留原命令标识并等待显式对账。`;
}

function parseResumePayload(
  text: string,
  incident: IndustrialIncident,
  decision: IndustrialIncidentDecisionReceipt,
): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("补证请求必须是一个 JSON 对象。");
  }
  const payload = parsed as Record<string, unknown>;
  if (
    typeof payload.schema_version !== "string" ||
    !incidentRequestSchemas.has(payload.schema_version)
  ) {
    throw new Error("仅接受 industrial-incident-request v1 / v2 / v3 合同。");
  }
  if (payload.operator_attests_inputs_authorized !== true) {
    throw new Error("请求必须显式包含 operator_attests_inputs_authorized=true。");
  }
  if (payload.raw_industrial_data_redistribution_allowed !== false) {
    throw new Error("请求必须保持 raw_industrial_data_redistribution_allowed=false。");
  }
  const expected = {
    supersedes_case_id: incident.case_id,
    expected_parent_case_sha256: incident.case_sha256,
    authorizing_decision_id: decision.decision_id,
  };
  for (const [field, expectedValue] of Object.entries(expected)) {
    const supplied = payload[field];
    if (supplied !== undefined && supplied !== null && supplied !== expectedValue) {
      throw new Error(`${field} 与当前不可变 Parent / Decision 绑定冲突。`);
    }
  }
  return { ...payload, ...expected };
}

function DecisionDialog({
  incident,
  submitting,
  onClose,
  onSubmit,
}: {
  incident: IndustrialIncident;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (input: {
    decision: IndustrialIncidentHumanDecision;
    note: string;
    selectedRemediationPlanId?: string;
  }) => Promise<void>;
}) {
  const [decision, setDecision] = useState<IndustrialIncidentHumanDecision>("CONTINUE_HOLD");
  const [note, setNote] = useState("");
  const [planId, setPlanId] = useState(incident.linked_remediation_plan_ids[0] ?? "");
  const [attested, setAttested] = useState(false);
  const [error, setError] = useState<string>();
  const planRequired = decision === "SELECT_REMEDIATION_PLAN";
  const canSubmit =
    attested &&
    note.trim().length >= 8 &&
    (!planRequired || Boolean(planId)) &&
    !submitting;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError(undefined);
    try {
      await onSubmit({
        decision,
        note: note.trim(),
        ...(planRequired ? { selectedRemediationPlanId: planId } : {}),
      });
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <Modal title="记录具名人工决定" onClose={submitting ? () => undefined : onClose}>
      <form className="live-incident-dialog" onSubmit={(event) => void submit(event)}>
        <div className="live-incident-dialog__binding">
          <ShieldCheck size={18} />
          <div><strong>{incident.case_id}</strong><small>bound case SHA · {compact(incident.case_sha256)}</small></div>
        </div>
        <label><span>决定</span><select value={decision} onChange={(event) => setDecision(event.target.value as IndustrialIncidentHumanDecision)}>
          {Object.entries(decisionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select></label>
        {planRequired ? (
          <label><span>服务端证据中已绑定的整改方案</span><select value={planId} onChange={(event) => setPlanId(event.target.value)} required>
            <option value="">选择方案</option>
            {incident.linked_remediation_plan_ids.map((item) => <option value={item} key={item}>{item}</option>)}
          </select></label>
        ) : null}
        <label><span>复核说明（至少 8 字）</span><textarea value={note} onChange={(event) => setNote(event.target.value)} rows={5} placeholder="说明已核对的证据、保留的竞争性解释与下一步责任人。" required /></label>
        <label className={attested ? "live-incident-attest is-checked" : "live-incident-attest"}>
          <input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} />
          <LockKeyhole size={15} />
          <span><strong>我已复核当前 Case 的证据与声明边界</strong><small>本决定不请求生产放行，不请求设备控制；写入后不可覆盖。</small></span>
        </label>
        {error ? <div className="live-incident-dialog__error"><AlertTriangle size={14} />{error}</div> : null}
        <footer><button type="button" onClick={onClose} disabled={submitting}>取消</button><button className="is-primary" type="submit" disabled={!canSubmit}>{submitting ? <LoaderCircle className="is-spinning" size={14} /> : <UserCheck size={14} />}{submitting ? "正在写入命令账本…" : "签署不可变决定"}</button></footer>
      </form>
    </Modal>
  );
}

function ResumeDialog({
  incident,
  decision,
  submitting,
  onClose,
  onSubmit,
}: {
  incident: IndustrialIncident;
  decision: IndustrialIncidentDecisionReceipt;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [payloadText, setPayloadText] = useState("");
  const [fileName, setFileName] = useState("");
  const [attested, setAttested] = useState(false);
  const [error, setError] = useState<string>();

  const loadFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      setError("JSON 文件超过 2 MiB，本地工作台已拒绝加载。");
      return;
    }
    try {
      const text = await file.text();
      parseResumePayload(text, incident, decision);
      setPayloadText(text);
      setFileName(file.name);
      setError(undefined);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const canSubmit = payloadText.trim().length > 0 && attested && !submitting;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError(undefined);
    try {
      await onSubmit(parseResumePayload(payloadText, incident, decision));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <Modal title="用新证据创建不可变 Child Case" onClose={submitting ? () => undefined : onClose}>
      <form className="live-incident-dialog" onSubmit={(event) => void submit(event)}>
        <div className="live-incident-dialog__binding">
          <RotateCcw size={18} />
          <div><strong>{incident.case_id} → NEW CHILD</strong><small>decision · {decision.decision_id}</small></div>
        </div>
        <label className="live-incident-file"><span>选择新的 Incident Request JSON（最大 2 MiB）</span><input type="file" accept="application/json,.json" onChange={(event) => void loadFile(event)} disabled={submitting} /><small>{fileName || "必须包含新的离线证据；工作台只补齐当前 Parent / Decision 三个血缘字段。"}</small></label>
        <label><span>补证合同预览</span><textarea value={payloadText} onChange={(event) => { setPayloadText(event.target.value); setFileName(""); }} rows={11} placeholder="粘贴 industrial-incident-request v1 / v2 / v3 JSON" required /></label>
        <label className={attested ? "live-incident-attest is-checked" : "live-incident-attest"}>
          <input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} />
          <LockKeyhole size={15} />
          <span><strong>我确认这是新的、已授权且已脱敏的离线证据</strong><small>服务端会拒绝未变化证据、错误血缘、跨产品身份或失效来源。</small></span>
        </label>
        {error ? <div className="live-incident-dialog__error"><AlertTriangle size={14} />{error}</div> : null}
        <footer><button type="button" onClick={onClose} disabled={submitting}>取消</button><button className="is-primary" type="submit" disabled={!canSubmit}>{submitting ? <LoaderCircle className="is-spinning" size={14} /> : <RefreshCw size={14} />}{submitting ? "正在执行新一轮受控 Agent…" : "验证并创建 Child Case"}</button></footer>
      </form>
    </Modal>
  );
}

function phaseReceiptSummary(
  events: IndustrialIncidentAuthoritySnapshot["phaseEvents"],
  phase: IndustrialIncidentAuthoritySnapshot["phaseEvents"][number]["phase"],
): { status: string; detail: string } {
  const matches = events.filter((event) => event.phase === phase);
  if (matches.length === 0) {
    return { status: "UNAVAILABLE", detail: `${phase} event 未返回` };
  }
  const statuses = matches.map((event) => event.status);
  const status = statuses.includes("FAILED")
    ? "FAILED"
    : statuses.includes("PAUSED")
      ? "PAUSED"
      : statuses.includes("STOPPED")
        ? "STOPPED"
        : "SUCCEEDED";
  const actors = [...new Set(matches.map((event) => event.actor))];
  return {
    status,
    detail: `${matches.length} event · ${actors.join(" / ")}`,
  };
}

function IncidentAuthorityBridge({
  snapshot,
  unavailableReason,
  incident,
}: {
  snapshot?: IndustrialIncidentAuthoritySnapshot;
  unavailableReason?: string;
  incident: IndustrialIncident;
}) {
  if (!snapshot) {
    return (
      <section
        className="incident-authority-bridge incident-authority-bridge--unavailable"
        role="alert"
      >
        <AlertTriangle size={22} />
        <div>
          <span>GOAL 3 · AUTHORITATIVE RECEIPTS</span>
          <h2>UNAVAILABLE · FAIL CLOSED</h2>
          <p>
            {unavailableReason ??
              "阶段、控制平面、审计封套或运行档案没有形成同一作用域的完整回执。"}
          </p>
          <small>不使用 fixture 补位；Case 基础账本仍可查看，但不能据此宣称内核回执已验真。</small>
        </div>
        <StatusBadge tone="danger">FAIL CLOSED</StatusBadge>
      </section>
    );
  }

  const planner = phaseReceiptSummary(snapshot.phaseEvents, "PLAN");
  const tool = phaseReceiptSummary(snapshot.phaseEvents, "ACT");
  const council = phaseReceiptSummary(snapshot.phaseEvents, "OBSERVE");
  const judge = phaseReceiptSummary(snapshot.phaseEvents, "EVALUATE");
  const delivery = phaseReceiptSummary(snapshot.phaseEvents, "INTERRUPT");
  const stages = [
    {
      label: "Intake",
      status: "BOUND",
      detail: `Case v${incident.case_version} · runtime profile bound`,
    },
    { label: "Planner", ...planner },
    { label: "Tool", ...tool },
    { label: "Council / Ledger", ...council },
    { label: "Policy Judge", ...judge },
    {
      label: "Delivery",
      status: delivery.status,
      detail: `audit sealed · ${delivery.detail}`,
    },
  ];
  const { controlPlane, auditEnvelope, runtimeProfileBinding } = snapshot;

  return (
    <section className="incident-authority-bridge" aria-label="Goal 3 内核权威回执">
      <header className="incident-authority-bridge__header">
        <div>
          <span>GOAL 3 · AUTHORITATIVE RECEIPTS</span>
          <h2>内核实物已绑定当前 Task / Case</h2>
          <p>
            四个只读接口并发核验；这里只展示可观察事件与封存回执，不显示隐藏思维链。
          </p>
        </div>
        <StatusBadge tone="success">RECEIPTS VERIFIED</StatusBadge>
      </header>

      <ol className="incident-authority-stages">
        {stages.map((stage, index) => (
          <li key={stage.label} data-status={stage.status.toLowerCase()}>
            <i>{String(index + 1).padStart(2, "0")}</i>
            <div>
              <span>{stage.label}</span>
              <strong>{stage.status}</strong>
              <small title={stage.detail}>{stage.detail}</small>
            </div>
          </li>
        ))}
      </ol>

      <div className="incident-authority-artifacts">
        <article>
          <header><Network size={14} /><span>CONTROL PLANE</span></header>
          <strong>
            {controlPlane.plan_tree.nodes.length} nodes · {controlPlane.plan_tree.selected_path_node_ids.length} selected
          </strong>
          <p>
            {controlPlane.plan_tree.dynamic_workers_executed}/{controlPlane.plan_tree.dynamic_worker_budget} workers · authority {controlPlane.authority_ledger.current_state.status.toLowerCase()} @ epoch {controlPlane.authority_ledger.current_state.authority_epoch}
          </p>
          <code title={controlPlane.bundle_sha256}>{compact(controlPlane.bundle_sha256, 14, 8)}</code>
        </article>
        <article>
          <header><LockKeyhole size={14} /><span>AUDIT ROOT</span></header>
          <strong>{auditEnvelope.phase_events.length} phase bindings · {auditEnvelope.signature.status}</strong>
          <p>{auditEnvelope.protocol.canonicalization_profile} · domain-framed</p>
          <code title={auditEnvelope.audit_root.value}>{compact(auditEnvelope.audit_root.value, 14, 8)}</code>
        </article>
        <article>
          <header><Bot size={14} /><span>RUNTIME PROFILE</span></header>
          <strong>{runtimeProfileBinding.profile.model_profile_id} · {runtimeProfileBinding.profile.planner_mode}</strong>
          <p>{runtimeProfileBinding.planner_connection_status} · memory {runtimeProfileBinding.profile.memory_mode}</p>
          <code title={runtimeProfileBinding.binding_sha256}>{compact(runtimeProfileBinding.binding_sha256, 14, 8)}</code>
        </article>
      </div>

      <footer className="incident-authority-safety">
        <span><ShieldCheck size={13} /> task / case / workspace / project · BOUND</span>
        <strong>production_release=false</strong>
        <strong>machine_write=false</strong>
        <strong>authority=human_only</strong>
      </footer>
    </section>
  );
}

export function LiveIncidentWorkbench({ taskId, caseId }: LiveIncidentWorkbenchProps) {
  const { activeWorkspace, activeProject, connection } = useProduct();
  const [loadState, setLoadState] = useState<LoadState>("LOADING");
  const [scope, setScope] = useState<LoadedIncidentScope>();
  const [error, setError] = useState<string>();
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [mutationReceipt, setMutationReceipt] = useState<IndustrialIncidentCommandResult<IndustrialIncident | IndustrialIncidentDecisionReceipt>>();
  const [commandReconciliation, setCommandReconciliation] = useState<IncidentCommandReconciliation>();
  const [reconcilingCommand, setReconcilingCommand] = useState(false);
  const generationRef = useRef(0);
  const mutationEpochRef = useRef(0);
  const mutationScopeKey = `${activeWorkspace?.workspace_id ?? "NO_WORKSPACE"}:${activeProject?.project_id ?? "NO_PROJECT"}:${taskId}:${caseId}`;
  const mutationScopeKeyRef = useRef(mutationScopeKey);
  mutationScopeKeyRef.current = mutationScopeKey;

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    setScope(undefined);
    setError(undefined);
    if (connection.api !== "CONNECTED") {
      setLoadState("NOT_CONNECTED");
      return;
    }
    if (!activeWorkspace || !activeProject) {
      setLoadState("ERROR");
      setError("请先选择工作空间与项目；案件深链接不会绕过当前作用域。");
      return;
    }
    if (!/^tsk_[0-9a-f]{20}$/.test(taskId) || !/^incident_[0-9a-f]{20}$/.test(caseId)) {
      setLoadState("ERROR");
      setError("案件深链接缺少有效的 task / incident 标识，已拒绝发起未绑定查询。");
      return;
    }
    setLoadState("LOADING");
    try {
      const task = await getAgentTask(taskId);
      if (
        task.workspace_id !== activeWorkspace.workspace_id ||
        task.project_id !== activeProject.project_id
      ) {
        throw new Error("请求的 Task 不属于当前 workspace / project，已拒绝跨作用域读取。");
      }
      const [incident, decisions, relatedCases] = await Promise.all([
        getIndustrialIncident(taskId, caseId),
        listIndustrialIncidentDecisions(taskId, caseId),
        listIndustrialIncidents(taskId),
      ]);
      const interactionCase = incident.parent_case_id
        ? incident
        : relatedCases.find((item) => item.parent_case_id === incident.case_id);
      const authorityRequest = getIndustrialIncidentAuthoritySnapshot({
        taskId,
        caseId,
        caseSha256: incident.case_sha256,
        workspaceId: task.workspace_id,
        projectId: task.project_id,
        caseStatus: incident.status,
        recommendation: incident.recommendation,
      });
      const interactionRequest = interactionCase
        ? getIndustrialIncidentInteractionReceipt(taskId, interactionCase.case_id)
        : Promise.resolve(undefined);
      const [authorityResult, interactionResult] = await Promise.allSettled([
        authorityRequest,
        interactionRequest,
      ]);
      const authoritySnapshot =
        authorityResult.status === "fulfilled" ? authorityResult.value : undefined;
      const authorityError =
        authorityResult.status === "rejected"
          ? errorMessage(authorityResult.reason)
          : undefined;
      const interaction =
        interactionResult.status === "fulfilled" ? interactionResult.value : undefined;
      const interactionError =
        interactionResult.status === "rejected"
          ? errorMessage(interactionResult.reason)
          : undefined;
      if (generation !== generationRef.current) return;
      setScope({
        task,
        incident,
        decisions,
        relatedCases,
        interaction,
        interactionError,
        authoritySnapshot,
        authorityError,
      });
      setLoadState("READY");
    } catch (caught) {
      if (generation !== generationRef.current) return;
      setLoadState("ERROR");
      setError(errorMessage(caught));
    }
  }, [activeProject, activeWorkspace, caseId, connection.api, taskId]);

  useEffect(() => {
    mutationEpochRef.current += 1;
    setDecisionOpen(false);
    setResumeOpen(false);
    setMutationReceipt(undefined);
    setCommandReconciliation(undefined);
    setMutating(false);
    setReconcilingCommand(false);
    void refresh();
    return () => {
      generationRef.current += 1;
    };
  }, [refresh]);

  const incident = scope?.incident;
  const decision = scope?.decisions[0];
  const child = useMemo(
    () => scope?.relatedCases.find((item) => item.parent_case_id === caseId),
    [caseId, scope?.relatedCases],
  );
  const simulated = incident?.request.opcua_snapshot.source_mode === "FIXTURE_REPLAY";

  const submitDecision = async (input: {
    decision: IndustrialIncidentHumanDecision;
    note: string;
    selectedRemediationPlanId?: string;
  }) => {
    if (!incident) return;
    const mutationEpoch = ++mutationEpochRef.current;
    const submittedScopeKey = mutationScopeKey;
    const isCurrentMutation = () => (
      mutationEpoch === mutationEpochRef.current
      && submittedScopeKey === mutationScopeKeyRef.current
    );
    setMutating(true);
    try {
      const idempotencyKey = await contentIdempotencyKey("web-incident-decision", {
        taskId,
        caseId,
        caseSha256: incident.case_sha256,
        ...input,
      });
      const anticipatedCommandId = await anticipatedIncidentCommandId({
        taskId,
        operation: "RECORD_DECISION",
        targetCaseId: caseId,
        idempotencyKey,
      });
      if (!isCurrentMutation()) return;
      setMutationReceipt(undefined);
      setCommandReconciliation({
        commandId: anticipatedCommandId,
        status: "PENDING",
        detail: "命令正在执行；在终态确认前不会生成新幂等键或自动重放。",
      });
      const result = await recordIndustrialIncidentDecision({
        taskId,
        caseId,
        boundCaseSha256: incident.case_sha256,
        idempotencyKey,
        ...input,
      });
      if (!isCurrentMutation()) return;
      setMutationReceipt(result);
      setCommandReconciliation(undefined);
      setDecisionOpen(false);
      await refresh();
    } catch (caught) {
      if (!isCurrentMutation()) return;
      if (isUnknownCommandOutcome(caught)) {
        setCommandReconciliation((current) => ({
          commandId: caught.incidentCommandId ?? current?.commandId ?? "",
          status: "PENDING",
          detail: unknownCommandOutcomeDetail(caught),
        }));
        setDecisionOpen(false);
        return;
      }
      setCommandReconciliation(undefined);
      throw caught;
    } finally {
      if (isCurrentMutation()) setMutating(false);
    }
  };

  const submitResume = async (payload: Record<string, unknown>) => {
    const mutationEpoch = ++mutationEpochRef.current;
    const submittedScopeKey = mutationScopeKey;
    const isCurrentMutation = () => (
      mutationEpoch === mutationEpochRef.current
      && submittedScopeKey === mutationScopeKeyRef.current
    );
    setMutating(true);
    try {
      const idempotencyKey = await contentIdempotencyKey("web-incident-resume", {
        taskId,
        caseId,
        payload,
      });
      const anticipatedCommandId = await anticipatedIncidentCommandId({
        taskId,
        operation: "RESUME_CASE",
        targetCaseId: caseId,
        idempotencyKey,
      });
      if (!isCurrentMutation()) return;
      setMutationReceipt(undefined);
      setCommandReconciliation({
        commandId: anticipatedCommandId,
        status: "PENDING",
        detail: "命令正在执行；在终态确认前不会生成新幂等键或自动重放。",
      });
      const result = await resumeIndustrialIncident({ taskId, caseId, payload, idempotencyKey });
      if (!isCurrentMutation()) return;
      setMutationReceipt(result);
      setCommandReconciliation(undefined);
      setResumeOpen(false);
      await refresh();
    } catch (caught) {
      if (!isCurrentMutation()) return;
      if (isUnknownCommandOutcome(caught)) {
        setCommandReconciliation((current) => ({
          commandId: caught.incidentCommandId ?? current?.commandId ?? "",
          status: "PENDING",
          detail: unknownCommandOutcomeDetail(caught),
        }));
        setResumeOpen(false);
        return;
      }
      setCommandReconciliation(undefined);
      throw caught;
    } finally {
      if (isCurrentMutation()) setMutating(false);
    }
  };

  const reconcileIncidentCommand = async () => {
    if (!commandReconciliation || reconcilingCommand) return;
    const mutationEpoch = ++mutationEpochRef.current;
    const submittedScopeKey = mutationScopeKey;
    const reconciledCommand = commandReconciliation;
    const isCurrentMutation = () => (
      mutationEpoch === mutationEpochRef.current
      && submittedScopeKey === mutationScopeKeyRef.current
    );
    setReconcilingCommand(true);
    try {
      const receipt = await getIndustrialIncidentCommand(
        taskId,
        reconciledCommand.commandId,
      );
      if (!isCurrentMutation()) return;
      const status: IncidentCommandViewStatus =
        receipt.status === "UNCERTAIN" ? "PENDING" : receipt.status;
      setCommandReconciliation({
        commandId: receipt.command_id,
        status,
        receipt,
        detail:
          receipt.status === "UNCERTAIN"
            ? "服务端原始状态 UNCERTAIN：尚无终态回执，继续保持 PENDING 且禁止自动重放。"
            : receipt.status === "COMPLETED"
              ? "服务端已核验不可变终态与资源摘要。"
              : `${receipt.error_code ?? "COMMAND_REJECTED"} · ${receipt.error_message ?? "命令已拒绝"}`,
      });
      if (receipt.status === "COMPLETED") await refresh();
    } catch (caught) {
      if (!isCurrentMutation()) return;
      setCommandReconciliation((current) =>
        current
          ? {
              ...current,
              status: "PENDING",
              detail: `对账查询未取得可验证终态：${errorMessage(caught)}`,
            }
          : current,
      );
    } finally {
      if (isCurrentMutation()) setReconcilingCommand(false);
    }
  };

  if (loadState !== "READY" || !scope || !incident) {
    return (
      <div className="live-incident-workbench live-incident-workbench--state">
        <Panel variant={loadState === "ERROR" ? "danger" : "raised"}>
          <PanelHeader eyebrow="LIVE INCIDENT" title={loadState === "LOADING" ? "正在核验案件绑定" : loadState === "NOT_CONNECTED" ? "本地 API 未连接" : "案件工作台不可用"} detail={loadState === "LOADING" ? "读取 Task、Case、Decision 与关联版本；不使用 fixture 补位。" : error ?? "连接 API 后再读取真实案件。"} />
          {loadState === "LOADING" ? <LoaderCircle className="is-spinning" size={22} /> : <AlertTriangle size={22} />}
          <div className="live-incident-state-actions"><Link to="/cases">返回案件</Link><button type="button" onClick={() => void refresh()}><RefreshCw size={13} /> 重试</button></div>
        </Panel>
      </div>
    );
  }

  return (
    <div className="live-incident-workbench">
      <header className="live-incident-heading">
        <div><Link to={`/cases?task=${encodeURIComponent(taskId)}&case=${encodeURIComponent(caseId)}&version=${incident.case_version}`}>← 返回案件收件箱</Link><span>INCIDENT V{incident.schema_version.endsWith(".v6") ? "6" : "5"} · VERSION {incident.case_version}</span><h1>{incident.case_id}</h1><p>{scope.task.goal}</p></div>
        <div><EvidenceSourceBadge source="LIVE_API" /><StatusBadge tone={tone(incident.status)}>{incident.status}</StatusBadge><ActionButton variant="secondary" icon={RefreshCw} onClick={() => void refresh()}>刷新账本</ActionButton></div>
      </header>

      {simulated ? (
        <section className="live-incident-simulated" role="alert">
          <AlertTriangle size={20} />
          <div><strong>SIMULATED EVIDENCE</strong><span>当前 OPC UA 输入为 FIXTURE_REPLAY，只能验证产品闭环；不得视为真实工厂影子证据。</span></div>
          <StatusBadge tone="danger">SIMULATED_EVIDENCE_SCOPE</StatusBadge>
        </section>
      ) : (
        <section className="live-incident-offline"><ShieldCheck size={17} /><span>AUTHORIZED OFFLINE EXPORT · 仍未连接真实 OPC UA / VisionMaster，生产权限始终为 false。</span></section>
      )}

      <IncidentAuthorityBridge
        snapshot={scope.authoritySnapshot}
        unavailableReason={scope.authorityError}
        incident={incident}
      />

      <IncidentReviewProjectionPanel
        taskId={taskId}
        caseId={caseId}
        initialProjection={scope.authoritySnapshot?.reviewProjection}
        surface="workbench"
      />

      {mutationReceipt ? (
        <section className="live-incident-command-receipt">
          <CheckCircle2 size={16} />
          <div><strong>不可变命令已完成并返回实体绑定</strong><span>{mutationReceipt.commandId}</span></div>
          <code>{compact(mutationReceipt.resourceSha256)}</code>
        </section>
      ) : null}

      {commandReconciliation ? (
        <section
          className={`live-incident-command-reconcile is-${commandReconciliation.status.toLowerCase()}`}
          role="status"
        >
          {commandReconciliation.status === "COMPLETED" ? (
            <CheckCircle2 size={17} />
          ) : (
            <AlertTriangle size={17} />
          )}
          <div>
            <strong>INCIDENT COMMAND · {commandReconciliation.status}</strong>
            <code>{commandReconciliation.commandId}</code>
            <span>{commandReconciliation.detail}</span>
            {commandReconciliation.receipt?.resource_sha256 ? (
              <small>resource SHA · {compact(commandReconciliation.receipt.resource_sha256)}</small>
            ) : null}
          </div>
          <StatusBadge tone={tone(commandReconciliation.status)} compact>
            {commandReconciliation.status}
          </StatusBadge>
          <button
            type="button"
            onClick={() => void reconcileIncidentCommand()}
            disabled={reconcilingCommand}
          >
            {reconcilingCommand ? (
              <LoaderCircle className="is-spinning" size={14} />
            ) : (
              <RefreshCw size={14} />
            )}
            {reconcilingCommand ? "正在查询" : "显式查询命令"}
          </button>
        </section>
      ) : null}

      <div className="live-incident-grid">
        <aside className="live-incident-left">
          <Panel>
            <PanelHeader eyebrow="CASE IDENTITY" title="案件与输入绑定" detail="所有标识来自当前服务端账本。" />
            <dl className="live-incident-kv">
              <div><dt>Task</dt><dd>{compact(taskId)}</dd></div>
              <div><dt>Case version</dt><dd>{incident.case_version}</dd></div>
              <div><dt>Source mode</dt><dd>{incident.request.opcua_snapshot.source_mode}</dd></div>
              <div><dt>Product / recipe</dt><dd>{incident.request.trigger.product_id} / {incident.request.trigger.recipe_id}</dd></div>
              <div><dt>Line / lot</dt><dd>{incident.request.trigger.line_id ?? "—"} / {incident.request.trigger.lot_reference ?? "—"}</dd></div>
              <div><dt>Root cause</dt><dd>{incident.root_cause_status}</dd></div>
            </dl>
            <Digest label="case SHA-256" value={incident.case_sha256} />
            <Digest label="evidence bundle" value={incident.evidence_bundle_sha256} />
            <Digest label="context" value={incident.context_sha256} />
          </Panel>

          <Panel>
            <PanelHeader eyebrow="BOUNDED LOOP" title="Agent 循环预算" detail="预算耗尽或证据不足时失败关闭。" />
            <div className="live-incident-loop-metrics"><span><strong>{incident.loop_control.current_iteration}/{incident.loop_control.max_iterations}</strong><small>iteration</small></span><span><strong>{incident.loop_control.dynamic_workers_executed}/{incident.loop_control.dynamic_worker_budget}</strong><small>workers</small></span><span><strong>{incident.loop_control.remaining_worker_budget}</strong><small>remaining</small></span></div>
            <p className="live-incident-stop"><CircleOff size={13} />{incident.loop_control.stop_reason}</p>
            {incident.loop_control.resume_requires.map((item) => <small className="live-incident-requirement" key={item}>requires · {item}</small>)}
          </Panel>

          <Panel>
            <PanelHeader eyebrow="LINEAGE" title="不可变案件版本" detail="Parent 不被覆盖；补证只创建新 Child Case。" />
            <div className="live-incident-lineage-node"><GitBranch size={15} /><div><strong>{incident.case_id}</strong><small>v{incident.case_version} · {compact(incident.case_sha256)}</small></div><StatusBadge tone={child ? "neutral" : "info"} compact>{child ? "PARENT" : "CURRENT"}</StatusBadge></div>
            {child ? <Link className="live-incident-child" to={`/cases/${encodeURIComponent(child.case_id)}?task=${encodeURIComponent(taskId)}`}><ArrowRight size={14} /><div><strong>{child.case_id}</strong><small>v{child.case_version} · {child.status}</small></div></Link> : <p className="live-incident-inline-empty">尚未创建 Child Case。</p>}
          </Panel>
        </aside>

        <main className="live-incident-center">
          {scope.task.source_kind === "synthetic_demo" ? (
            <Panel className="task-visual-evidence task-visual-evidence--state">
              <PanelHeader
                eyebrow="SAMPLE SCOPE · SYNTHETIC"
                title="Task 冻结视觉分母未声明"
                detail="当前案件使用项目级合成上下文验证 Agent 闭环；不会请求只适用于已授权真实来源的 Task Visual Evidence。"
                actions={<StatusBadge tone="warning" compact>NOT CLAIMED</StatusBadge>}
              />
              <ClaimBoundary title="视觉证据边界" tone="info">
                合成前后对比只在评审页作为项目级演示资产展示，不计入工厂效果、客户验收或真实 Task 冻结视觉分母。
              </ClaimBoundary>
            </Panel>
          ) : (
            <TaskVisualEvidencePanel
              taskId={taskId}
              expectedWorkspaceId={scope.task.workspace_id}
              expectedProjectId={scope.task.project_id}
            />
          )}

          <Panel variant="raised">
            <PanelHeader eyebrow="AUDITABLE RECOMMENDATION" title={incident.recommendation} detail={incident.recommendation_reason} actions={<StatusBadge tone={tone(incident.planning_mode)} compact>{incident.planning_mode}</StatusBadge>} />
            <div className="live-incident-next-action"><Bot size={17} /><div><span>NEXT SAFE ACTION</span><strong>{incident.decision_summary.next_safe_action}</strong></div></div>
            <div className="live-incident-summary-columns"><section><header><CheckCircle2 size={13} /> 已观察事实</header>{incident.decision_summary.observed_facts.map((item) => <p key={item}>{item}</p>)}</section><section><header><Network size={13} /> 保留的竞争性解释</header>{incident.decision_summary.alternatives_kept_open.map((item) => <p key={item}>{item}</p>)}</section></div>
          </Panel>

          <Panel>
            <PanelHeader eyebrow="EVIDENCE ISSUES" title="证据缺口与责任动作" detail={`${incident.evidence_issues.length} 条服务端持久化 issue；不把缺口写成根因。`} />
            <div className="live-incident-issue-list">{incident.evidence_issues.map((issue, index) => <article className={issue.severity === "BLOCKING" ? "is-blocking" : ""} key={`${issue.issue_code}:${index}`}><div><StatusBadge tone={issue.severity === "BLOCKING" ? "danger" : "warning"} compact>{issue.severity}</StatusBadge><code>{issue.issue_code}</code></div><strong>{issue.summary}</strong><p>{issue.required_evidence_or_action}</p><small>{issue.worker_role} · blocks disposition {String(issue.blocks_disposition)}</small></article>)}</div>
          </Panel>

          <Panel>
            <PanelHeader eyebrow="AGENT / WORKER RECEIPTS" title="真实执行链" detail="展示动作与 Worker 回执，不展示私有思维链。" />
            <div className="live-incident-action-list">{incident.agent_actions.map((action) => <article key={`${action.sequence}:${action.agent_role}`}><span>{String(action.sequence).padStart(2, "0")}</span><div><strong>{action.action}</strong><small>{action.agent_role} · iteration {action.iteration}</small></div><StatusBadge tone={tone(action.status)} compact>{action.status}</StatusBadge></article>)}</div>
            <details className="live-incident-worker-details"><summary><Wrench size={13} /> {incident.worker_receipts.length} 个 Worker receipt</summary>{incident.worker_receipts.map((receipt) => <p key={receipt.invocation_id}><StatusBadge tone={receipt.status === "FAILED" ? "danger" : "success"} compact>{receipt.status}</StatusBadge><strong>{receipt.worker_role}</strong><span>attempt {receipt.attempt}</span><code>{compact(receipt.receipt_sha256)}</code></p>)}</details>
          </Panel>
        </main>

        <aside className="live-incident-right">
          <Panel variant="danger">
            <PanelHeader eyebrow="HUMAN AUTHORITY" title="人工决定闸门" detail="Agent 只有建议权；同一 Case 只允许一个不可变决定。" />
            <div className="live-incident-authority"><span><UserCheck size={13} /> human approval</span><strong>REQUIRED</strong><span><LockKeyhole size={13} /> production release</span><strong>FALSE</strong><span><CircleOff size={13} /> machine write</span><strong>FALSE</strong></div>
            {!decision ? <ActionButton icon={UserCheck} disabled={commandReconciliation?.status === "PENDING"} onClick={() => setDecisionOpen(true)}>{commandReconciliation?.status === "PENDING" ? "等待命令对账" : "记录具名人工决定"}</ActionButton> : <div className="live-incident-decision"><header><CheckCircle2 size={14} /><span>DECISION SEALED</span></header><strong>{decision.decision}</strong><p>{decision.note}</p><small>{decision.actor_user_id} · {new Date(decision.decided_at).toLocaleString("zh-CN")}</small><Digest label="decision SHA" value={decision.decision_sha256} />{decision.linked_capa_case_id ? <Link to={`/capa?task=${encodeURIComponent(taskId)}&case=${encodeURIComponent(decision.linked_capa_case_id)}&layer=controlled`}><Wrench size={13} /> 打开已建立的 CAPA <ArrowRight size={13} /></Link> : null}</div>}
            {decision && incident.loop_control.can_resume && !child ? <ActionButton variant="secondary" icon={RotateCcw} disabled={commandReconciliation?.status === "PENDING"} onClick={() => setResumeOpen(true)}>{commandReconciliation?.status === "PENDING" ? "等待命令对账" : "导入新证据并恢复"}</ActionButton> : null}
            {child ? <StatusBadge tone="info">PARENT ALREADY ADVANCED</StatusBadge> : null}
          </Panel>

          <Panel>
            <PanelHeader eyebrow="DELIVERY" title="证据与工作流入口" detail="所有链接继续绑定当前 Task / Case。" />
            <div className="live-incident-links"><Link to={`/evidence?task=${encodeURIComponent(taskId)}&case=${encodeURIComponent(caseId)}&version=${incident.case_version}`}><Download size={14} /> Decision Packet / Audit Bundle</Link><Link to={`/command-center?task=${encodeURIComponent(taskId)}`}><Bot size={14} /> 打开对应 Agent Task</Link><Link to={`/lineage?task=${encodeURIComponent(taskId)}`}><GitBranch size={14} /> 查看 Task / CAPA 血缘</Link><Link to={`/runs?task=${encodeURIComponent(taskId)}`}><Network size={14} /> 查看运行事件</Link></div>
          </Panel>

          <Panel>
            <PanelHeader eyebrow="OPERATOR QUESTIONS" title="待补证问题" detail={`${incident.operator_questions.length} 条结构化中断。`} />
            <div className="live-incident-question-list">{incident.operator_questions.map((question) => <article key={question.question_id}><Siren size={13} /><div><strong>{question.prompt}</strong><small>{question.expected_evidence_type} · {question.reason_codes.join(" · ")}</small></div><StatusBadge tone={question.required ? "danger" : "warning"} compact>{question.status}</StatusBadge></article>)}</div>
          </Panel>
        </aside>
      </div>

      {scope.interaction ? (
        <IncidentInteractionTimeline receipt={scope.interaction} />
      ) : scope.interactionError ? (
        <section className="live-incident-interaction-error" role="alert">
          <AlertTriangle size={16} />
          <div>
            <strong>三轮交互回执不可用</strong>
            <span>{scope.interactionError}</span>
          </div>
          <StatusBadge tone="danger" compact>FAIL CLOSED</StatusBadge>
        </section>
      ) : null}

      <ClaimBoundary title="案件工作台边界" tone="danger">{incident.claim_boundary} 当前页面可以记录具名人工决定、选择 CAPA 和用新证据创建 Child Case，但永远不会把这些动作升级为生产放行或设备控制。</ClaimBoundary>

      {decisionOpen ? <DecisionDialog incident={incident} submitting={mutating} onClose={() => setDecisionOpen(false)} onSubmit={submitDecision} /> : null}
      {resumeOpen && decision ? <ResumeDialog incident={incident} decision={decision} submitting={mutating} onClose={() => setResumeOpen(false)} onSubmit={submitResume} /> : null}
    </div>
  );
}
