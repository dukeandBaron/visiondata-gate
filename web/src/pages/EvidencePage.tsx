import {
  AlertTriangle,
  Archive,
  Bot,
  Check,
  CheckCircle2,
  CircleOff,
  Copy,
  Download,
  FileArchive,
  FileCheck2,
  FileJson2,
  Fingerprint,
  HardDriveDownload,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldCheck,
  Waypoints,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { AgentTask, IndustrialIncident } from "../agentDomain";
import { ClaimBoundary, EvidenceSourceBadge, PageIntro, StatusBadge } from "../components/ui";
import { listAgentTasks, listIndustrialIncidentV5, operatorFetch } from "../data/api";
import type { StatusTone } from "../domain";
import { useProduct } from "../ProductContext";

type LoadState = "IDLE" | "LOADING" | "READY" | "ERROR";
type DownloadState = "IDLE" | "DOWNLOADING" | "SAVED" | "ERROR";
type ArtifactTarget =
  | "evidenceZip"
  | "runtimeTrace"
  | "decisionPacketHtml"
  | "auditBundle";

interface ArtifactDownloadState {
  status: DownloadState;
  message?: string;
  verifiedSha256?: string;
  verificationMode?: "BYTE_SHA256" | "PACKET_IDENTITY_HEADER";
}

interface DecisionPacketState {
  status: "IDLE" | "CHECKING" | "AVAILABLE" | "UNAVAILABLE";
  packetSha256?: string;
  schemaVersion?: string;
  message?: string;
}

const sha256Pattern = /^[0-9a-f]{64}$/;
const artifactTargets: ArtifactTarget[] = [
  "evidenceZip",
  "runtimeTrace",
  "decisionPacketHtml",
  "auditBundle",
];

function initialArtifactDownloads(): Record<ArtifactTarget, ArtifactDownloadState> {
  return {
    evidenceZip: { status: "IDLE" },
    runtimeTrace: { status: "IDLE" },
    decisionPacketHtml: { status: "IDLE" },
    auditBundle: { status: "IDLE" },
  };
}

function hasSha256(value: string | null | undefined): value is string {
  return typeof value === "string" && sha256Pattern.test(value);
}

function compactId(value: string, head = 10, tail = 6): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "未知 API 错误";
}

function statusTone(value: string | null | undefined): StatusTone {
  const normalized = (value ?? "").toUpperCase();
  if (/FAILED|BLOCKED|STOPPED|HOLD|REJECT|CANCEL/.test(normalized)) return "danger";
  if (/PENDING|WAIT|RECAPTURE|REVIEW|PLANNED|CREATED/.test(normalized)) return "warning";
  if (/COMPLETED|PASS|SUCCEEDED|SUPPORTED|CURRENT|AVAILABLE/.test(normalized)) return "success";
  if (/RUNNING|VERIFYING|DISPATCHED/.test(normalized)) return "info";
  return "neutral";
}

function businessDecision(task: AgentTask): { label: string; source: string } {
  if (task.final_decision) return { label: task.final_decision, source: "final decision" };
  if (task.initial_decision) return { label: task.initial_decision, source: "initial decision" };
  return { label: "NOT ISSUED", source: "no business decision" };
}

function artifactReady(task: AgentTask, kind: "trace" | "evidence"): boolean {
  if (kind === "trace") return hasSha256(task.trace_sha256) && Boolean(task.trace_rel);
  return hasSha256(task.evidence_sha256) && Boolean(task.evidence_zip_rel);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("当前浏览器不支持 Web Crypto SHA-256 校验。");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

function requiredShaHeader(response: Response, headerName: string): string {
  const value = response.headers.get(headerName)?.trim().replaceAll('"', "").toLowerCase();
  if (!hasSha256(value)) {
    throw new Error(`服务端未返回有效的 ${headerName}。`);
  }
  return value;
}

function saveArtifactBytes(bytes: ArrayBuffer, mediaType: string, filename: string): void {
  const objectUrl = URL.createObjectURL(new Blob([bytes], { type: mediaType }));
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

function HashRow({ label, value }: { label: string; value?: string | null }) {
  const [copied, setCopied] = useState(false);
  const available = hasSha256(value);

  const copy = async () => {
    if (!available) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={`live-evidence-hash-row${available ? "" : " is-unavailable"}`}>
      <span>{label}</span>
      <code title={available ? value : undefined}>{available ? value : "UNAVAILABLE"}</code>
      <button type="button" disabled={!available} onClick={copy} aria-label={`复制 ${label}`}>
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
    </div>
  );
}

export function EvidencePage() {
  const { activeWorkspace, activeProject, connection, workspaceLoading } = useProduct();
  const [searchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const requestedCaseId = searchParams.get("case")?.trim() ?? "";
  const requestedVersion = searchParams.get("version")?.trim() ?? "";
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [query, setQuery] = useState("");
  const [taskState, setTaskState] = useState<LoadState>("IDLE");
  const [taskError, setTaskError] = useState<string>();
  const [scopeNotice, setScopeNotice] = useState<string>();
  const [incidents, setIncidents] = useState<IndustrialIncident[]>([]);
  const [selectedIncidentKey, setSelectedIncidentKey] = useState("");
  const [incidentState, setIncidentState] = useState<LoadState>("IDLE");
  const [incidentError, setIncidentError] = useState<string>();
  const [packetState, setPacketState] = useState<DecisionPacketState>({ status: "IDLE" });
  const [artifactDownloads, setArtifactDownloads] = useState(initialArtifactDownloads);
  const [refreshToken, setRefreshToken] = useState(0);
  const taskGeneration = useRef(0);
  const incidentGeneration = useRef(0);
  const packetGeneration = useRef(0);
  const artifactDownloadGenerations = useRef<Record<ArtifactTarget, number>>({
    evidenceZip: 0,
    runtimeTrace: 0,
    decisionPacketHtml: 0,
    auditBundle: 0,
  });

  const workspaceId = activeWorkspace?.workspace_id;
  const projectId = activeProject?.project_id;
  const scopeKey = `${workspaceId ?? ""}::${projectId ?? ""}`;

  useEffect(() => {
    const generation = taskGeneration.current + 1;
    taskGeneration.current = generation;
    setTasks([]);
    setSelectedTaskId("");
    setTaskError(undefined);
    setScopeNotice(undefined);
    setTaskState("IDLE");

    if (!workspaceId || !projectId || connection.api !== "CONNECTED") return;

    setTaskState("LOADING");
    void listAgentTasks(workspaceId, projectId)
      .then((response) => {
        if (taskGeneration.current !== generation) return;
        const scoped = response
          .filter(
            (task) => task.workspace_id === workspaceId && task.project_id === projectId,
          )
          .sort(
            (left, right) =>
              new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
          );
        setTasks(scoped);
        const requested = scoped.find((task) => task.task_id === requestedTaskId);
        if (requestedTaskId && !requested) {
          setSelectedTaskId("");
          setScopeNotice(
            "深链接 Task 不属于当前 workspace / project，已拒绝展示其他任务作为替代。",
          );
        } else {
          setSelectedTaskId(requested?.task_id ?? scoped[0]?.task_id ?? "");
        }
        setTaskState("READY");
      })
      .catch((error: unknown) => {
        if (taskGeneration.current !== generation) return;
        setTaskError(errorMessage(error));
        setTaskState("ERROR");
      });

    return () => {
      if (taskGeneration.current === generation) taskGeneration.current += 1;
    };
  }, [connection.api, projectId, refreshToken, requestedTaskId, workspaceId]);

  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId);

  useEffect(() => {
    const generation = incidentGeneration.current + 1;
    incidentGeneration.current = generation;
    setIncidents([]);
    setSelectedIncidentKey("");
    setIncidentError(undefined);
    setIncidentState("IDLE");

    if (
      !selectedTask ||
      selectedTask.workspace_id !== workspaceId ||
      selectedTask.project_id !== projectId ||
      connection.api !== "CONNECTED"
    ) {
      return;
    }

    const taskId = selectedTask.task_id;
    setIncidentState("LOADING");
    void listIndustrialIncidentV5(taskId)
      .then((response) => {
        if (incidentGeneration.current !== generation) return;
        const scoped = response
          .filter((incident) => incident.task_id === taskId)
          .sort((left, right) => right.case_version - left.case_version);
        setIncidents(scoped);
        const hasIncidentDeepLink = Boolean(requestedCaseId || requestedVersion);
        const requested = hasIncidentDeepLink
          ? scoped.find((incident) => (
              (!requestedCaseId || incident.case_id === requestedCaseId) &&
              (!requestedVersion || String(incident.case_version) === requestedVersion)
            ))
          : undefined;
        if (hasIncidentDeepLink && !requested) {
          setSelectedIncidentKey("");
          setScopeNotice(
            "深链接 Incident 不属于所选 Task，或指定版本不存在；已拒绝展示其他案件作为替代。",
          );
        } else {
          const first = requested ?? scoped[0];
          setSelectedIncidentKey(first ? `${first.case_id}:${first.case_version}` : "");
        }
        setIncidentState("READY");
      })
      .catch((error: unknown) => {
        if (incidentGeneration.current !== generation) return;
        setIncidentError(errorMessage(error));
        setIncidentState("ERROR");
      });

    return () => {
      if (incidentGeneration.current === generation) incidentGeneration.current += 1;
    };
  }, [connection.api, projectId, requestedCaseId, requestedVersion, selectedTask?.task_id, workspaceId]);

  const selectedIncident =
    incidents.find(
      (incident) => `${incident.case_id}:${incident.case_version}` === selectedIncidentKey,
    );
  const artifactScopeKey = `${scopeKey}::${selectedTask?.task_id ?? ""}::${selectedIncidentKey}`;
  const artifactScopeRef = useRef(artifactScopeKey);
  artifactScopeRef.current = artifactScopeKey;

  useEffect(() => {
    const generation = packetGeneration.current + 1;
    packetGeneration.current = generation;
    setPacketState({ status: "IDLE" });

    if (!selectedTask || !selectedIncident || connection.api !== "CONNECTED") return;

    const taskId = selectedTask.task_id;
    const caseId = selectedIncident.case_id;
    setPacketState({ status: "CHECKING" });
    void operatorFetch(
      `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/decision-packet`,
    )
      .then(async (response) => {
        const payload = (await response.json()) as unknown;
        if (packetGeneration.current !== generation) return;
        if (!isRecord(payload) || !hasSha256(String(payload.packet_sha256 ?? ""))) {
          setPacketState({
            status: "UNAVAILABLE",
            message: "服务端响应缺少可验证的 packet_sha256。",
          });
          return;
        }
        setPacketState({
          status: "AVAILABLE",
          packetSha256: String(payload.packet_sha256),
          schemaVersion:
            typeof payload.schema_version === "string" ? payload.schema_version : undefined,
        });
      })
      .catch((error: unknown) => {
        if (packetGeneration.current !== generation) return;
        setPacketState({ status: "UNAVAILABLE", message: errorMessage(error) });
      });

    return () => {
      if (packetGeneration.current === generation) packetGeneration.current += 1;
    };
  }, [connection.api, selectedIncident?.case_id, selectedIncident?.case_version, selectedTask?.task_id]);

  useEffect(() => {
    artifactTargets.forEach((target) => {
      artifactDownloadGenerations.current[target] += 1;
    });
    setArtifactDownloads(initialArtifactDownloads());
  }, [artifactScopeKey]);

  const visibleTasks = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return tasks.filter((task) =>
      !normalized
        ? true
        : [
            task.task_id,
            task.goal,
            task.execution_status,
            task.final_decision,
            task.initial_decision,
            task.request_sha256,
            task.evidence_sha256,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(normalized),
    );
  }, [query, tasks]);

  const evidenceCount = tasks.filter((task) => artifactReady(task, "evidence")).length;
  const traceCount = tasks.filter((task) => artifactReady(task, "trace")).length;
  const currentDecision = selectedTask ? businessDecision(selectedTask) : undefined;
  const evidenceAvailable = selectedTask ? artifactReady(selectedTask, "evidence") : false;
  const traceAvailable = selectedTask ? artifactReady(selectedTask, "trace") : false;
  const packetAvailable =
    packetState.status === "AVAILABLE" && hasSha256(packetState.packetSha256);

  const downloadArtifact = async (
    target: ArtifactTarget,
    options: {
      path: string;
      shaHeader: string;
      filename: string;
      mediaType: string;
      label: string;
      expectedSha256?: string;
      verifyResponseBytes: boolean;
      byteShaHeader?: string;
    },
  ) => {
    const generation = artifactDownloadGenerations.current[target] + 1;
    artifactDownloadGenerations.current[target] = generation;
    const expectedScope = artifactScopeKey;
    setArtifactDownloads((current) => ({
      ...current,
      [target]: { status: "DOWNLOADING" },
    }));

    try {
      const response = await operatorFetch(options.path, {}, 120_000);
      const returnedSha = requiredShaHeader(response, options.shaHeader);
      if (options.expectedSha256 && returnedSha !== options.expectedSha256) {
        throw new Error(`${options.label} 的服务端 SHA 与当前证据账本不一致。`);
      }
      const returnedByteSha = options.byteShaHeader
        ? requiredShaHeader(response, options.byteShaHeader)
        : returnedSha;
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength === 0) {
        throw new Error(`${options.label} 返回了空文件。`);
      }
      if (options.verifyResponseBytes) {
        const computedSha = await sha256Hex(bytes);
        if (computedSha !== returnedByteSha) {
          throw new Error(`${options.label} 的浏览器字节 SHA 与服务端响应头不一致。`);
        }
      }
      if (
        artifactDownloadGenerations.current[target] !== generation ||
        artifactScopeRef.current !== expectedScope
      ) {
        return;
      }
      saveArtifactBytes(
        bytes,
        response.headers.get("Content-Type") ?? options.mediaType,
        options.filename,
      );
      setArtifactDownloads((current) => ({
        ...current,
        [target]: {
          status: "SAVED",
          verifiedSha256: options.verifyResponseBytes ? returnedByteSha : returnedSha,
          verificationMode: options.verifyResponseBytes
            ? "BYTE_SHA256"
            : "PACKET_IDENTITY_HEADER",
          message: options.verifyResponseBytes
            ? `${options.label} 响应字节 SHA-256 已核验。`
            : `${options.label} 已匹配当前 Decision Packet 身份 SHA。`,
        },
      }));
    } catch (error) {
      if (
        artifactDownloadGenerations.current[target] !== generation ||
        artifactScopeRef.current !== expectedScope
      ) {
        return;
      }
      setArtifactDownloads((current) => ({
        ...current,
        [target]: { status: "ERROR", message: errorMessage(error) },
      }));
    }
  };

  const downloadEvidence = () => {
    if (!selectedTask || !evidenceAvailable || !selectedTask.evidence_sha256) return;
    void downloadArtifact("evidenceZip", {
      path: `/v1/tasks/${encodeURIComponent(selectedTask.task_id)}/evidence`,
      shaHeader: "X-Evidence-SHA256",
      filename: `${selectedTask.task_id}-evidence.zip`,
      mediaType: "application/zip",
      label: "Evidence ZIP",
      expectedSha256: selectedTask.evidence_sha256,
      verifyResponseBytes: true,
    });
  };

  const downloadRuntimeTrace = () => {
    if (!selectedTask || !traceAvailable || !selectedTask.trace_sha256) return;
    void downloadArtifact("runtimeTrace", {
      path: `/v1/tasks/${encodeURIComponent(selectedTask.task_id)}/trace`,
      shaHeader: "X-Trace-SHA256",
      filename: `${selectedTask.task_id}-runtime-trace.json`,
      mediaType: "application/json",
      label: "Runtime Trace",
      expectedSha256: selectedTask.trace_sha256,
      verifyResponseBytes: true,
    });
  };

  const downloadDecisionPacketHtml = () => {
    const packetSha = packetState.packetSha256;
    if (!selectedTask || !selectedIncident || !packetAvailable || !hasSha256(packetSha)) return;
    void downloadArtifact("decisionPacketHtml", {
      path: `/v1/tasks/${encodeURIComponent(selectedTask.task_id)}/industrial-incidents/${encodeURIComponent(selectedIncident.case_id)}/decision-packet.html`,
      shaHeader: "X-Decision-Packet-SHA256",
      filename: `${selectedIncident.case_id}-decision-packet.html`,
      mediaType: "text/html",
      label: "Decision Packet HTML",
      expectedSha256: packetSha,
      verifyResponseBytes: true,
      byteShaHeader: "X-Content-SHA256",
    });
  };

  const downloadAuditBundle = () => {
    if (!selectedTask || !selectedIncident || !packetAvailable) return;
    void downloadArtifact("auditBundle", {
      path: `/v1/tasks/${encodeURIComponent(selectedTask.task_id)}/industrial-incidents/${encodeURIComponent(selectedIncident.case_id)}/decision-packet/audit-bundle`,
      shaHeader: "X-Audit-Bundle-SHA256",
      filename: `${selectedIncident.case_id}-decision-packet.zip`,
      mediaType: "application/zip",
      label: "Decision Packet Audit Bundle",
      verifyResponseBytes: true,
    });
  };

  const noScope = !activeWorkspace || !activeProject;
  const apiUnavailable = connection.api !== "CONNECTED";

  return (
    <div className="page-stack live-evidence-page">
      <PageIntro
        eyebrow="EVIDENCE / LIVE VAULT"
        title="证据库"
        description="按当前工作空间与项目读取真实 Task、运行 Trace、Evidence ZIP 和 Incident v5/v6；执行完成与业务放行始终分开呈现。"
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
          <button
            className="live-evidence-refresh"
            type="button"
            disabled={taskState === "LOADING" || noScope || apiUnavailable}
            onClick={() => setRefreshToken((value) => value + 1)}
          >
            <RefreshCw className={taskState === "LOADING" ? "is-spinning" : ""} size={14} />
            刷新证据索引
          </button>
        }
      />

      <section className="live-evidence-metrics" aria-label="当前项目证据概览">
        <article><Archive size={15} /><span>真实 Task</span><strong>{tasks.length}</strong></article>
        <article><FileArchive size={15} /><span>Evidence ZIP</span><strong>{evidenceCount}</strong></article>
        <article><FileJson2 size={15} /><span>Runtime Trace</span><strong>{traceCount}</strong></article>
        <article><Waypoints size={15} /><span>当前 Incident</span><strong>{incidents.length}</strong></article>
      </section>

      {taskState === "ERROR" ? (
        <div className="live-evidence-global-error" role="alert">
          <AlertTriangle size={15} />
          <div><strong>Task 证据索引读取失败</strong><span>{taskError}</span></div>
          <button type="button" onClick={() => setRefreshToken((value) => value + 1)}>重试</button>
        </div>
      ) : null}

      {scopeNotice ? (
        <div className="live-evidence-global-error" role="status">
          <AlertTriangle size={15} />
          <div><strong>实体定位被拒绝</strong><span>{scopeNotice}</span></div>
        </div>
      ) : null}

      <section className="live-evidence-workbench">
        <aside className="live-evidence-index">
          <header>
            <div><span>VAULT INDEX</span><strong>任务证据</strong></div>
            <small>{visibleTasks.length} / {tasks.length}</small>
          </header>
          <label className="live-evidence-search">
            <Search size={13} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索 Task / SHA / 裁决"
            />
          </label>
          <div className="live-evidence-task-list">
            {workspaceLoading || taskState === "LOADING" ? (
              <div className="live-evidence-empty is-compact">
                <LoaderCircle className="is-spinning" size={18} />
                <strong>读取证据索引</strong>
                <p>结果绑定当前 workspace / project。</p>
              </div>
            ) : apiUnavailable ? (
              <div className="live-evidence-empty is-compact is-danger">
                <CircleOff size={18} /><strong>本地 API 未连接</strong><p>不加载 fixture。</p>
              </div>
            ) : noScope ? (
              <div className="live-evidence-empty is-compact">
                <Archive size={18} /><strong>请先选择项目</strong><p>证据不会跨项目合并。</p>
              </div>
            ) : taskState === "ERROR" ? (
              <div className="live-evidence-empty is-compact is-danger">
                <AlertTriangle size={18} /><strong>索引不可用</strong><p>{taskError}</p>
              </div>
            ) : visibleTasks.length > 0 ? (
              visibleTasks.map((task) => {
                const decision = businessDecision(task);
                return (
                  <button
                    type="button"
                    key={task.task_id}
                    className={selectedTask?.task_id === task.task_id ? "is-active" : ""}
                    onClick={() => {
                      setScopeNotice(undefined);
                      setSelectedTaskId(task.task_id);
                    }}
                  >
                    <span className={`live-evidence-task-dot is-${statusTone(task.execution_status)}`} />
                    <div>
                      <strong>{task.goal}</strong>
                      <code title={task.task_id}>{compactId(task.task_id, 12, 5)}</code>
                      <small>{formatTime(task.updated_at)} · {decision.label}</small>
                    </div>
                    <span className="live-evidence-task-artifacts" aria-label="证据可用性">
                      <i className={artifactReady(task, "trace") ? "is-ready" : ""}>T</i>
                      <i className={artifactReady(task, "evidence") ? "is-ready" : ""}>E</i>
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="live-evidence-empty is-compact">
                <Archive size={18} />
                <strong>{tasks.length > 0 ? "没有匹配任务" : "当前项目没有 Task"}</strong>
                <p>{tasks.length > 0 ? "调整搜索词。" : "这里不会用预设证据补位。"}</p>
              </div>
            )}
          </div>
        </aside>

        <main className="live-evidence-manifest">
          {!selectedTask ? (
            <div className="live-evidence-empty">
              <Fingerprint size={22} />
              <strong>选择一个真实 Task 查看证据</strong>
              <p>只有服务端持久化的 SHA 与工件状态会出现在这里。</p>
            </div>
          ) : (
            <>
              <header className="live-evidence-task-header">
                <div>
                  <span>TASK EVIDENCE MANIFEST</span>
                  <h2>{selectedTask.goal}</h2>
                  <p>{selectedTask.task_id}</p>
                </div>
                <StatusBadge tone={statusTone(selectedTask.execution_status)} compact>
                  {selectedTask.execution_status}
                </StatusBadge>
              </header>

              <section className="live-evidence-decision-split">
                <article>
                  <header><Bot size={13} />确定性执行状态</header>
                  <strong>{selectedTask.execution_status}</strong>
                  <p>phase · {selectedTask.current_phase || "UNAVAILABLE"}</p>
                  <small>runtime · {selectedTask.runtime_status ?? "UNAVAILABLE"}</small>
                </article>
                <div aria-hidden="true"><LockKeyhole size={14} /></div>
                <article className="is-business">
                  <header><ShieldCheck size={13} />业务裁决</header>
                  <strong>{currentDecision?.label}</strong>
                  <p>{currentDecision?.source}</p>
                  <small>Task 完成不等于生产放行。</small>
                </article>
              </section>

              <section className="live-evidence-ledger">
                <header><Fingerprint size={14} /><span>IDENTITY LEDGER</span><small>SHA-256</small></header>
                <HashRow label="REQUEST" value={selectedTask.request_sha256} />
                <HashRow label="TRACE" value={selectedTask.trace_sha256} />
                <HashRow label="EVIDENCE" value={selectedTask.evidence_sha256} />
              </section>

              <section className="live-evidence-artifacts">
                <header><HardDriveDownload size={14} /><span>SERVER ARTIFACTS</span></header>
                <div>
                  <article className={evidenceAvailable ? "is-ready" : "is-unavailable"}>
                    <FileArchive size={17} />
                    <div><strong>Evidence ZIP</strong><small>{evidenceAvailable ? "header + byte SHA-256" : "UNAVAILABLE"}</small></div>
                    {evidenceAvailable ? (
                      <button
                        type="button"
                        disabled={artifactDownloads.evidenceZip.status === "DOWNLOADING"}
                        onClick={downloadEvidence}
                      >
                        {artifactDownloads.evidenceZip.status === "DOWNLOADING" ? <LoaderCircle className="is-spinning" size={13} /> : <Download size={13} />}
                        {artifactDownloads.evidenceZip.status === "DOWNLOADING" ? "校验中" : "下载 ZIP"}
                      </button>
                    ) : <span><CircleOff size={12} /> unavailable</span>}
                    {artifactDownloads.evidenceZip.status === "SAVED" ? (
                      <p className="live-evidence-artifact-result is-success"><CheckCircle2 size={11} />{artifactDownloads.evidenceZip.message}<code>{compactId(artifactDownloads.evidenceZip.verifiedSha256 ?? "", 8, 6)}</code></p>
                    ) : null}
                    {artifactDownloads.evidenceZip.status === "ERROR" ? (
                      <p className="live-evidence-artifact-result is-danger"><AlertTriangle size={11} />{artifactDownloads.evidenceZip.message}</p>
                    ) : null}
                  </article>
                  <article className={traceAvailable ? "is-ready" : "is-unavailable"}>
                    <FileJson2 size={17} />
                    <div><strong>Runtime Trace</strong><small>{traceAvailable ? "JSON header + byte SHA-256" : "UNAVAILABLE"}</small></div>
                    {traceAvailable ? (
                      <button
                        type="button"
                        disabled={artifactDownloads.runtimeTrace.status === "DOWNLOADING"}
                        onClick={downloadRuntimeTrace}
                      >
                        {artifactDownloads.runtimeTrace.status === "DOWNLOADING" ? <LoaderCircle className="is-spinning" size={13} /> : <Download size={13} />}
                        {artifactDownloads.runtimeTrace.status === "DOWNLOADING" ? "校验中" : "下载 Trace"}
                      </button>
                    ) : <span><CircleOff size={12} /> unavailable</span>}
                    {artifactDownloads.runtimeTrace.status === "SAVED" ? (
                      <p className="live-evidence-artifact-result is-success"><CheckCircle2 size={11} />{artifactDownloads.runtimeTrace.message}<code>{compactId(artifactDownloads.runtimeTrace.verifiedSha256 ?? "", 8, 6)}</code></p>
                    ) : null}
                    {artifactDownloads.runtimeTrace.status === "ERROR" ? (
                      <p className="live-evidence-artifact-result is-danger"><AlertTriangle size={11} />{artifactDownloads.runtimeTrace.message}</p>
                    ) : null}
                  </article>
                  <article className={packetAvailable ? "is-ready" : "is-unavailable"}>
                    <FileCheck2 size={17} />
                    <div>
                      <strong>Decision Packet HTML</strong>
                      <small>
                        {packetState.status === "CHECKING"
                          ? "checking server endpoint"
                          : packetAvailable
                            ? "Packet identity header bound"
                            : "UNAVAILABLE"}
                      </small>
                    </div>
                    {packetState.status === "CHECKING" ? <span><LoaderCircle className="is-spinning" size={12} /> checking</span> : null}
                    {packetAvailable ? (
                      <button
                        type="button"
                        disabled={artifactDownloads.decisionPacketHtml.status === "DOWNLOADING"}
                        onClick={downloadDecisionPacketHtml}
                      >
                        {artifactDownloads.decisionPacketHtml.status === "DOWNLOADING" ? <LoaderCircle className="is-spinning" size={13} /> : <Download size={13} />}
                        {artifactDownloads.decisionPacketHtml.status === "DOWNLOADING" ? "核对中" : "下载 HTML"}
                      </button>
                    ) : packetState.status !== "CHECKING" ? <span><CircleOff size={12} /> unavailable</span> : null}
                    {artifactDownloads.decisionPacketHtml.status === "SAVED" ? (
                      <p className="live-evidence-artifact-result is-success"><CheckCircle2 size={11} />{artifactDownloads.decisionPacketHtml.message}<code>{compactId(artifactDownloads.decisionPacketHtml.verifiedSha256 ?? "", 8, 6)}</code></p>
                    ) : null}
                    {artifactDownloads.decisionPacketHtml.status === "ERROR" ? (
                      <p className="live-evidence-artifact-result is-danger"><AlertTriangle size={11} />{artifactDownloads.decisionPacketHtml.message}</p>
                    ) : null}
                  </article>
                  <article className={packetAvailable ? "is-ready" : "is-unavailable"}>
                    <Archive size={17} />
                    <div><strong>Audit Bundle</strong><small>{packetAvailable ? "ZIP header + byte SHA-256" : "UNAVAILABLE"}</small></div>
                    {packetAvailable ? (
                      <button
                        type="button"
                        disabled={artifactDownloads.auditBundle.status === "DOWNLOADING"}
                        onClick={downloadAuditBundle}
                      >
                        {artifactDownloads.auditBundle.status === "DOWNLOADING" ? <LoaderCircle className="is-spinning" size={13} /> : <Download size={13} />}
                        {artifactDownloads.auditBundle.status === "DOWNLOADING" ? "校验中" : "下载审计包"}
                      </button>
                    ) : <span><CircleOff size={12} /> unavailable</span>}
                    {artifactDownloads.auditBundle.status === "SAVED" ? (
                      <p className="live-evidence-artifact-result is-success"><CheckCircle2 size={11} />{artifactDownloads.auditBundle.message}<code>{compactId(artifactDownloads.auditBundle.verifiedSha256 ?? "", 8, 6)}</code></p>
                    ) : null}
                    {artifactDownloads.auditBundle.status === "ERROR" ? (
                      <p className="live-evidence-artifact-result is-danger"><AlertTriangle size={11} />{artifactDownloads.auditBundle.message}</p>
                    ) : null}
                  </article>
                </div>
              </section>

              <section className="live-evidence-incident-list">
                <header>
                  <div><Waypoints size={14} /><span>INCIDENT V5/V6 CASE HASHES</span></div>
                  <small>{incidentState === "LOADING" ? "loading" : `${incidents.length} cases`}</small>
                </header>
                {incidentState === "LOADING" ? (
                  <p><LoaderCircle className="is-spinning" size={13} />读取 Incident v5/v6</p>
                ) : incidentState === "ERROR" ? (
                  <p className="is-danger"><AlertTriangle size={13} />Incident endpoint unavailable · {incidentError}</p>
                ) : incidents.length > 0 ? (
                  <div>
                    {incidents.map((incident) => {
                      const key = `${incident.case_id}:${incident.case_version}`;
                      return (
                        <button
                          type="button"
                          key={key}
                          className={selectedIncident?.case_id === incident.case_id && selectedIncident.case_version === incident.case_version ? "is-active" : ""}
                          onClick={() => setSelectedIncidentKey(key)}
                        >
                          <span>v{incident.case_version}</span>
                          <div><strong>{incident.case_id}</strong><code title={incident.case_sha256}>{compactId(incident.case_sha256, 12, 8)}</code></div>
                          <StatusBadge tone={statusTone(incident.status)} compact>{incident.status}</StatusBadge>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p><CircleOff size={13} />UNAVAILABLE · 当前 Task 未返回 Incident v5/v6。</p>
                )}
              </section>
            </>
          )}
        </main>

        <aside className="live-evidence-inspector">
          {selectedTask && selectedIncident ? (
            <>
              <header>
                <span>CASE INSPECTOR · V{selectedIncident.case_version}</span>
                <strong>{selectedIncident.case_id}</strong>
                <StatusBadge tone={statusTone(selectedIncident.status)} compact>{selectedIncident.status}</StatusBadge>
              </header>

              <section className="live-evidence-case-seal">
                <div><Fingerprint size={16} /><span>INCIDENT CASE SHA</span></div>
                <code title={selectedIncident.case_sha256}>{selectedIncident.case_sha256}</code>
              </section>

              <section className="live-evidence-inspector-section">
                <header><span>PLANNING RECEIPTS</span></header>
                <HashRow label="BELIEF LEDGER" value={selectedIncident.planning_belief_ledger.ledger_sha256} />
                <HashRow label="EVIDENCE BUNDLE" value={selectedIncident.planning_belief_ledger.evidence_bundle_sha256} />
                <HashRow label="WORKER SELECT" value={selectedIncident.worker_selection_receipt.receipt_sha256} />
                <HashRow label="DECISION PACKET" value={packetState.packetSha256} />
              </section>

              <section className="live-evidence-inspector-section">
                <header><span>DETERMINISTIC WORKERS</span><small>{selectedIncident.worker_selection_receipt.selected_worker_ids.length}</small></header>
                <div className="live-evidence-worker-list">
                  {selectedIncident.worker_selection_receipt.selected_worker_ids.length > 0 ? (
                    selectedIncident.worker_selection_receipt.selected_worker_ids.map((worker) => (
                      <span key={worker}><CheckCircle2 size={11} />{worker}</span>
                    ))
                  ) : <p>UNAVAILABLE · 无 selected worker。</p>}
                </div>
              </section>

              <section className="live-evidence-inspector-section">
                <header><span>WORKER RECEIPTS</span><small>{selectedIncident.worker_receipts.length}</small></header>
                <div className="live-evidence-receipts">
                  {selectedIncident.worker_receipts.length > 0 ? selectedIncident.worker_receipts.map((receipt) => (
                    <article className={receipt.status === "FAILED" ? "is-failed" : ""} key={receipt.invocation_id}>
                      <div><strong>{receipt.worker_role}</strong><StatusBadge tone={statusTone(receipt.status)} compact>{receipt.status}</StatusBadge></div>
                      <code title={receipt.receipt_sha256}>{compactId(receipt.receipt_sha256, 9, 7)}</code>
                      {receipt.status === "FAILED" ? <p>{receipt.error_code ?? "WORKER_EXECUTION_FAILED"} · retryable {String(receipt.retryable)}</p> : null}
                    </article>
                  )) : <p className="live-evidence-inline-empty">UNAVAILABLE · 尚未产生 Worker receipt。</p>}
                </div>
              </section>

              <section className="live-evidence-safety">
                <header><LockKeyhole size={13} />HUMAN AUTHORITY</header>
                <div><span>人工批准</span><strong>{selectedIncident.human_approval_required ? "REQUIRED" : "NOT REQUIRED"}</strong></div>
                <div><span>生产放行</span><strong>{String(selectedIncident.production_release_allowed).toUpperCase()}</strong></div>
                <div><span>设备写入</span><strong>{String(selectedIncident.machine_write_permitted).toUpperCase()}</strong></div>
              </section>

              {packetState.status === "UNAVAILABLE" ? (
                <div className="live-evidence-packet-error" role="status">
                  <CircleOff size={12} />Decision Packet unavailable · {packetState.message}
                </div>
              ) : null}
            </>
          ) : (
            <div className="live-evidence-empty is-compact">
              <LockKeyhole size={20} />
              <strong>没有可检查的 Incident</strong>
              <p>Task 证据仍可独立核验；不会构造案件或 Decision Packet。</p>
            </div>
          )}
        </aside>
      </section>

      <ClaimBoundary title="证据库边界" tone="info">
        本页不读取 fixture，不展示服务端本地绝对路径，也不把 SHA-256 描述为数字签名或可信时间戳；所有业务裁决仍需具名人工复核。
      </ClaimBoundary>
    </div>
  );
}
