import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleOff,
  GitBranch,
  Link2,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";
import type {
  IncidentReviewProjection,
  IncidentReviewWorker,
} from "../agentDomain";
import type { ControlledCapaCase } from "../capaDomain";
import {
  readIndustrialIncidentReviewProjection,
  type IncidentReviewReadState,
  type IncidentReviewReadStatus,
} from "../data/api";
import {
  readControlledCapaCase,
  type ControlledCapaReadState,
  type ControlledCapaReadStatus,
} from "../data/capaApi";
import type { StatusTone } from "../domain";
import { Digest, StatusBadge } from "./ui";
import "../styles/incident-review-projection.css";

interface IncidentReviewProjectionPanelProps {
  taskId: string;
  caseId: string;
  initialProjection?: IncidentReviewProjection;
  surface: "reviewer" | "workbench";
}

type ProjectionStatus = IncidentReviewReadStatus | "READING";
type CapaStatus = ControlledCapaReadStatus | "READING";

const projectionStatusCopy: Record<
  ProjectionStatus,
  { title: string; detail: string; tone: StatusTone }
> = {
  READING: {
    title: "READING",
    detail: "正在执行只读 GET 与 SHA 合同核验。",
    tone: "info",
  },
  VERIFIED: {
    title: "VERIFIED",
    detail: "当前响应已通过作用域、摘要与只读权限合同。",
    tone: "success",
  },
  NOT_CREATED: {
    title: "NOT_CREATED",
    detail: "当前 Task / Case 尚未形成评审投影；可在上游完成后重试。",
    tone: "warning",
  },
  STALE_HOLD: {
    title: "STALE_HOLD",
    detail: "刷新未取得当前版本；旧值只供对照，不再视为 PASS。",
    tone: "danger",
  },
  RETRYABLE_UNAVAILABLE: {
    title: "RETRYABLE_UNAVAILABLE",
    detail: "本地 API 暂不可用；恢复连接后可重试只读 GET。",
    tone: "warning",
  },
  CONTRACT_HOLD: {
    title: "CONTRACT_HOLD",
    detail: "响应未通过前端合同核验；禁止沿用为已验证事实。",
    tone: "danger",
  },
};

function compact(value: string | null | undefined, head = 10, tail = 6): string {
  if (!value) return "—";
  return value.length > head + tail + 1
    ? `${value.slice(0, head)}…${value.slice(-tail)}`
    : value;
}

function domainTone(value: string): StatusTone {
  const normalized = value.toUpperCase();
  if (/FAILED|BLOCK|HOLD|REJECT|STALE|TRANSFERRED/.test(normalized)) return "danger";
  if (/WAIT|PENDING|RECAPTURE|REVIEW|REQUIRED|SELECTED/.test(normalized)) return "warning";
  if (/PASS|COMPLETE|SUCCEEDED|RECOVERED|APPROVED|VERIFIED/.test(normalized)) return "success";
  if (/RUNNING|DISPATCH|READY|CREATED/.test(normalized)) return "info";
  return "neutral";
}

function sortWorkers(workers: IncidentReviewWorker[]): IncidentReviewWorker[] {
  return [...workers].sort((left, right) => {
    if (left.rank === null && right.rank === null) return left.worker_id.localeCompare(right.worker_id);
    if (left.rank === null) return 1;
    if (right.rank === null) return -1;
    return left.rank - right.rank;
  });
}

function displayProjection(
  state: IncidentReviewReadState | undefined,
): IncidentReviewProjection | undefined {
  return state?.value ?? state?.retainedVerifiedValue;
}

function displayCapa(
  state: ControlledCapaReadState | undefined,
): ControlledCapaCase | undefined {
  return state?.value ?? state?.retainedVerifiedValue;
}

function errorDetail(state: IncidentReviewReadState | ControlledCapaReadState | undefined): string {
  if (!state?.error) return "";
  return `${state.error.code} · ${state.error.message}`;
}

function capaMatchesProjection(
  link: IncidentReviewProjection["capa_cases"][number],
  capa: ControlledCapaCase,
): boolean {
  return (
    link.case_id === capa.case_id &&
    link.selection_sha256 === capa.selection.selection_sha256 &&
    link.approval_binding_sha256 === (capa.approval?.binding_sha256 ?? null) &&
    link.child_task_id === (capa.execution?.child_task_id ?? null) &&
    link.child_evidence_sha256 === (capa.execution?.child_evidence_sha256 ?? null) &&
    link.child_lineage_report_sha256 ===
      (capa.execution?.child_lineage_report_sha256 ?? null) &&
    link.execution_receipt_sha256 === (capa.execution?.receipt_sha256 ?? null) &&
    link.recovery_receipt_sha256 === (capa.recovery?.receipt_sha256 ?? null)
  );
}

function WorkerCard({
  worker,
  triggerReasonCodes = [],
  stale,
}: {
  worker: IncidentReviewWorker;
  triggerReasonCodes?: string[];
  stale: boolean;
}) {
  return (
    <article className={worker.selected ? "is-selected" : "is-rejected"}>
      <header>
        <span>{worker.rank === null ? "UNRANKED" : `RANK ${worker.rank}`}</span>
        <StatusBadge
          tone={stale ? "warning" : worker.selected ? "success" : "neutral"}
          compact
        >
          {stale ? "STALE" : worker.selected ? "SELECTED" : "REJECTED"}
        </StatusBadge>
      </header>
      <strong>{worker.worker_id}</strong>
      <dl>
        <div><dt>blocking severity</dt><dd>{worker.blocking_severity}</dd></div>
        <div><dt>measured cost</dt><dd>{worker.measured_cost_bucket}</dd></div>
        <div>
          <dt>discriminates</dt>
          <dd>{worker.discriminated_hypothesis_ids.join(" · ") || "NONE RECORDED"}</dd>
        </div>
        <div>
          <dt>unresolved evidence</dt>
          <dd>{worker.unresolved_evidence_refs.join(" · ") || "NONE RECORDED"}</dd>
        </div>
      </dl>
      <div className="incident-review-worker__reasons">
        <span>
          {worker.selected
            ? "SELECTION POLICY REASONS"
            : "SELECTION POLICY / EXCLUSION REASONS"}
        </span>
        {worker.reason_codes.map((reason) => <code key={reason}>{reason}</code>)}
      </div>
      {worker.selected ? (
        <div className="incident-review-worker__reasons">
          <span>EXECUTION TRIGGER REASONS</span>
          {triggerReasonCodes.length ? (
            triggerReasonCodes.map((reason, index) => (
              <code key={`${reason}:${index}`}>{reason}</code>
            ))
          ) : (
            <code>NONE RECORDED</code>
          )}
        </div>
      ) : null}
    </article>
  );
}

function EmptyFact({ children }: { children: string }) {
  return <p className="incident-review-empty"><CircleOff size={14} />{children}</p>;
}

export function IncidentReviewProjectionPanel({
  taskId,
  caseId,
  initialProjection,
  surface,
}: IncidentReviewProjectionPanelProps) {
  const seed = initialProjection?.task_id === taskId && initialProjection.case_id === caseId
    ? initialProjection
    : undefined;
  const [reviewState, setReviewState] = useState<IncidentReviewReadState | undefined>(() =>
    seed
      ? { status: "VERIFIED", value: seed, retryable: false }
      : undefined,
  );
  const [loading, setLoading] = useState(true);
  const [capaStates, setCapaStates] = useState<Record<string, ControlledCapaReadState>>({});
  const [capaLoadingIds, setCapaLoadingIds] = useState<string[]>([]);
  const previousProjectionRef = useRef<IncidentReviewProjection | undefined>(seed);
  const previousCapaRef = useRef<Record<string, ControlledCapaCase>>({});
  const generationRef = useRef(0);

  const readCapa = useCallback(async (capaCaseId: string, generation: number) => {
    if (generation !== generationRef.current) return;
    setCapaLoadingIds((current) =>
      current.includes(capaCaseId) ? current : [...current, capaCaseId],
    );
    try {
      const next = await readControlledCapaCase(
        taskId,
        capaCaseId,
        previousCapaRef.current[capaCaseId],
      );
      if (generation !== generationRef.current) return;
      if (next.status === "VERIFIED" && next.value) {
        previousCapaRef.current[capaCaseId] = next.value;
      }
      setCapaStates((current) => ({ ...current, [capaCaseId]: next }));
    } finally {
      if (generation === generationRef.current) {
        setCapaLoadingIds((current) => current.filter((item) => item !== capaCaseId));
      }
    }
  }, [taskId]);

  const refreshProjection = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    try {
      const next = await readIndustrialIncidentReviewProjection(
        taskId,
        caseId,
        previousProjectionRef.current,
      );
      if (generation !== generationRef.current) return;
      if (next.status === "VERIFIED" && next.value) {
        previousProjectionRef.current = next.value;
      }
      setReviewState(next);
      const projection = displayProjection(next);
      if (!projection) {
        previousCapaRef.current = {};
        setCapaStates({});
        return;
      }
      const linkedIds = projection.capa_cases.map((item) => item.case_id);
      const capaIds = [...new Set([
        ...linkedIds,
        ...projection.missing_linked_capa_case_ids,
      ])];
      const nextPrevious: Record<string, ControlledCapaCase> = {};
      capaIds.forEach((id) => {
        const previous = previousCapaRef.current[id];
        if (previous) nextPrevious[id] = previous;
      });
      previousCapaRef.current = nextPrevious;
      setCapaStates((current) => Object.fromEntries(
        capaIds.flatMap((id) => current[id] ? [[id, current[id]]] : []),
      ));
      await Promise.all(capaIds.map((id) => readCapa(id, generation)));
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [caseId, readCapa, taskId]);

  useEffect(() => {
    generationRef.current += 1;
    previousProjectionRef.current = seed;
    previousCapaRef.current = {};
    setReviewState(seed
      ? { status: "VERIFIED", value: seed, retryable: false }
      : undefined);
    setCapaStates({});
    setCapaLoadingIds([]);
    void refreshProjection();
    return () => {
      generationRef.current += 1;
    };
  }, [caseId, initialProjection?.projection_sha256, refreshProjection, taskId]);

  const projection = displayProjection(reviewState);
  const readStatus: ProjectionStatus = reviewState?.status ?? "READING";
  const statusCopy = projectionStatusCopy[readStatus];
  const retainedStale = Boolean(
    reviewState?.retainedVerifiedValue && reviewState.status !== "VERIFIED",
  );
  const projectionVerified = reviewState?.status === "VERIFIED";
  const selectedWorkers = useMemo(
    () => sortWorkers(projection?.selected_workers ?? []),
    [projection],
  );
  const rejectedWorkers = useMemo(
    () => sortWorkers(projection?.rejected_workers ?? []),
    [projection],
  );
  const selectedWorkerTriggerReasons = useMemo(
    () => new Map(
      (projection?.triggering_evidence ?? []).map((trigger) => [
        trigger.worker_role,
        trigger.trigger_reason_codes,
      ] as const),
    ),
    [projection],
  );
  const capaIds = useMemo(() => projection ? [...new Set([
    ...projection.capa_cases.map((item) => item.case_id),
    ...projection.missing_linked_capa_case_ids,
  ])] : [], [projection]);

  const retryCapa = (capaCaseId: string) => {
    if (capaLoadingIds.includes(capaCaseId)) return;
    void readCapa(capaCaseId, generationRef.current);
  };

  return (
    <section
      className={`incident-review-projection incident-review-projection--${surface}${retainedStale ? " is-stale" : ""}`}
      data-read-status={readStatus}
      aria-busy={loading || capaLoadingIds.length > 0}
    >
      <header className="incident-review-projection__heading">
        <div>
          <span>GOAL 2 · PERSISTED REVIEW PROJECTION</span>
          <h2>Agent 路由、证据与闭环事实</h2>
          <p>只投影服务端已持久化事实；不补写路由理由、不推断根因、不授予生产权限。</p>
        </div>
        <div className="incident-review-projection__heading-actions">
          <StatusBadge tone={retainedStale ? "danger" : statusCopy.tone}>
            {loading && projectionVerified ? "VERIFYING" : statusCopy.title}
            {retainedStale ? " · STALE" : ""}
          </StatusBadge>
          <button type="button" onClick={() => void refreshProjection()} disabled={loading}>
            {loading ? <LoaderCircle className="is-spinning" size={14} /> : <RefreshCw size={14} />}
            {loading ? "GET 核验中" : "重新 GET 核验"}
          </button>
        </div>
      </header>

      <div className={`incident-review-read-state is-${readStatus.toLowerCase()}`} role="status" aria-live="polite">
        {readStatus === "VERIFIED" ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
        <div>
          <strong>{statusCopy.title}{retainedStale ? " · STALE DISPLAY" : ""}</strong>
          <span>{statusCopy.detail}</span>
          {errorDetail(reviewState) ? <code>{errorDetail(reviewState)}</code> : null}
        </div>
      </div>

      {projection ? (
        <>
          <div className="incident-review-source-rail" aria-label="投影来源边界">
            <span>
              <strong>LOCAL API TRANSPORT</strong>
              <em>{projection.transport_source_mode}</em>
              <small>LIVE 仅表示当前本地 API 读取</small>
            </span>
            <span>
              <strong>EVIDENCE MODE</strong>
              <em>{projection.evidence_source_mode}</em>
              <small>{projection.evidence_source_mode === "REPLAY"
                ? "冻结回放证据"
                : projection.evidence_source_mode === "OFFLINE_EXPORT"
                  ? "授权离线导出"
                  : "未识别的证据模式"}</small>
            </span>
            <span className="is-factory-offline">
              <strong>FACTORY CONNECTION</strong>
              <em>{projection.factory_live_connection_claimed ? "CLAIMED" : "NOT CLAIMED"}</em>
              <small>未声明真实 OPC UA / VisionMaster 在线</small>
            </span>
            <span>
              <strong>AUTHORITY</strong>
              <em>READ ONLY</em>
              <small>production=false · machine_write=false</small>
            </span>
          </div>

          <section className="incident-review-workers" aria-labelledby={`worker-routing-${surface}`}>
            <header>
              <div>
                <span>01 · WORKER SELECTION</span>
                <h3 id={`worker-routing-${surface}`}>排序、选择与排除依据</h3>
              </div>
              <div>
                <StatusBadge tone={projectionVerified ? "info" : "warning"} compact>
                  BUDGET {selectedWorkers.length}/{projection.worker_budget}
                </StatusBadge>
                <code title="Worker selection receipt SHA-256">
                  SEL {compact(projection.worker_selection_receipt_sha256)}
                </code>
                <code title="Agent behavior receipt SHA-256">
                  BEH {compact(projection.agent_behavior_receipt_sha256)}
                </code>
              </div>
            </header>
            <div className="incident-review-worker-lanes">
              <section>
                <header><Bot size={14} /><strong>SELECTED</strong><span>{selectedWorkers.length}</span></header>
                {selectedWorkers.length ? selectedWorkers.map((worker) => (
                  <WorkerCard
                    key={worker.worker_id}
                    worker={worker}
                    triggerReasonCodes={selectedWorkerTriggerReasons.get(worker.worker_id)}
                    stale={!projectionVerified}
                  />
                )) : <EmptyFact>服务端未记录入选 Worker。</EmptyFact>}
              </section>
              <section className="is-rejected">
                <header><CircleOff size={14} /><strong>REJECTED</strong><span>{rejectedWorkers.length}</span></header>
                {rejectedWorkers.length ? rejectedWorkers.map((worker) => (
                  <WorkerCard key={worker.worker_id} worker={worker} stale={!projectionVerified} />
                )) : <EmptyFact>服务端未记录被排除 Worker。</EmptyFact>}
              </section>
            </div>
          </section>

          <div className="incident-review-evidence-grid">
            <section>
              <header><span>02 · TRIGGERING EVIDENCE</span><strong>Worker 调用回执</strong></header>
              <div className="incident-review-trigger-list">
                {projection.triggering_evidence.length ? projection.triggering_evidence.map((trigger) => (
                  <article key={trigger.invocation_id}>
                    <div>
                      <StatusBadge tone={!projectionVerified ? "warning" : domainTone(trigger.status)} compact>
                        {!projectionVerified ? "STALE" : trigger.status}
                      </StatusBadge>
                      <code>{compact(trigger.receipt_sha256)}</code>
                    </div>
                    <strong>{trigger.worker_role}</strong>
                    <small>{trigger.trigger_reason_codes.join(" · ") || "NO TRIGGER CODE"}</small>
                    <em>{trigger.input_evidence_sha256.length} input evidence SHA</em>
                  </article>
                )) : <EmptyFact>没有已持久化的 triggering evidence。</EmptyFact>}
              </div>
            </section>

            <section>
              <header><span>03 · COMPETING HYPOTHESES</span><strong>竞争解释与区分测试</strong></header>
              <div className="incident-review-hypotheses">
                {projection.competing_hypotheses.length ? projection.competing_hypotheses.map((hypothesis) => (
                  <article key={hypothesis.hypothesis_id}>
                    <div>
                      <code>{hypothesis.hypothesis_id}</code>
                      <StatusBadge tone={!projectionVerified ? "warning" : domainTone(hypothesis.status)} compact>
                        {!projectionVerified ? `STALE · ${hypothesis.status}` : hypothesis.status}
                      </StatusBadge>
                    </div>
                    <strong>{hypothesis.category}</strong>
                    <p><span>支持</span>{hypothesis.supporting_issue_codes.join(" · ") || "NONE RECORDED"}</p>
                    <p><span>反证</span>{hypothesis.contradicting_issue_codes.join(" · ") || "NONE RECORDED"}</p>
                    <p><span>缺口</span>{hypothesis.unresolved_evidence_refs.join(" · ") || "NONE RECORDED"}</p>
                    <small>next test · {hypothesis.next_discriminating_test}</small>
                  </article>
                )) : <EmptyFact>没有已持久化的竞争假设。</EmptyFact>}
              </div>
            </section>
          </div>

          <div className="incident-review-decision-grid">
            <section>
              <header><AlertTriangle size={14} /><strong>MISSING EVIDENCE</strong><span>{projection.missing_evidence_refs.length}</span></header>
              {projection.missing_evidence_refs.length ? (
                <ul>{projection.missing_evidence_refs.map((item) => <li key={item}>{item}</li>)}</ul>
              ) : <EmptyFact>投影未记录缺失证据。</EmptyFact>}
            </section>
            <section>
              <header><ShieldCheck size={14} /><strong>WHAT WOULD CHANGE THE DECISION</strong><span>{projection.what_would_change_decision.length}</span></header>
              {projection.what_would_change_decision.length ? (
                <ul>{projection.what_would_change_decision.map((item) => <li key={item}>{item}</li>)}</ul>
              ) : <EmptyFact>投影未记录决策改变条件。</EmptyFact>}
            </section>
          </div>

          <section className="incident-review-lineage" aria-labelledby={`review-lineage-${surface}`}>
            <header>
              <div>
                <span>04 · GOVERNED LINEAGE</span>
                <h3 id={`review-lineage-${surface}`}>Parent / Human / Child / CAPA / Task</h3>
              </div>
              <StatusBadge tone={projectionVerified ? "success" : "warning"} compact>
                {projectionVerified ? "CURRENT PROJECTION" : "STALE PROJECTION"}
              </StatusBadge>
            </header>

            <div className="incident-review-case-flow">
              <section>
                <header><GitBranch size={14} /><strong>CASE VERSIONS</strong></header>
                {projection.parent_case ? (
                  <Link to={`/cases/${encodeURIComponent(projection.parent_case.case_id)}?task=${encodeURIComponent(taskId)}`}>
                    <span>PARENT · V{projection.parent_case.case_version}</span>
                    <strong>{projection.parent_case.case_id}</strong>
                    <small>{projectionVerified ? projection.parent_case.status : `STALE · ${projection.parent_case.status}`} · {compact(projection.parent_case.case_sha256)}</small>
                  </Link>
                ) : <EmptyFact>当前 Case 没有 Parent Case。</EmptyFact>}
                <article className="is-current">
                  <span>CURRENT · V{projection.current_case.case_version}</span>
                  <strong>{projection.current_case.case_id}</strong>
                  <small>{projectionVerified ? projection.current_case.status : `STALE · ${projection.current_case.status}`} · {compact(projection.current_case.case_sha256)}</small>
                </article>
                {projection.child_cases.map((child) => (
                  <Link key={child.case_id} to={`/cases/${encodeURIComponent(child.case_id)}?task=${encodeURIComponent(taskId)}`}>
                    <span>CHILD · V{child.case_version}</span>
                    <strong>{child.case_id}</strong>
                    <small>{projectionVerified ? child.status : `STALE · ${child.status}`} · {compact(child.case_sha256)}</small>
                  </Link>
                ))}
              </section>

              <ArrowRight className="incident-review-flow-arrow" size={18} aria-hidden="true" />

              <section>
                <header><UserCheck size={14} /><strong>HUMAN AUTHORITY</strong></header>
                {projection.human_decisions.length ? projection.human_decisions.map((decision) => (
                  <article key={decision.decision_id}>
                    <span>{decision.actor_user_id}</span>
                    <strong>{decision.decision}</strong>
                    <small>{decision.linked_capa_case_id ? `CAPA · ${decision.linked_capa_case_id}` : "NO LINKED CAPA"}</small>
                    <code>{compact(decision.decision_sha256)}</code>
                  </article>
                )) : <EmptyFact>尚未记录具名人工决定。</EmptyFact>}
              </section>

              <ArrowRight className="incident-review-flow-arrow" size={18} aria-hidden="true" />

              <section>
                <header><Wrench size={14} /><strong>CAPA / CHILD TASK</strong></header>
                {capaIds.length ? capaIds.map((capaCaseId) => {
                  const link = projection.capa_cases.find((item) => item.case_id === capaCaseId);
                  const state = capaStates[capaCaseId];
                  const capa = displayCapa(state);
                  const status: CapaStatus = capaLoadingIds.includes(capaCaseId)
                    ? "READING"
                    : state?.status ?? "READING";
                  const stale = Boolean(state?.retainedVerifiedValue && state.status !== "VERIFIED");
                  const bindingMatches = Boolean(link && capa && capaMatchesProjection(link, capa));
                  const chainVerified = projectionVerified && state?.status === "VERIFIED" && bindingMatches;
                  const statusMeta = projectionStatusCopy[status];
                  return (
                    <article className={chainVerified ? "is-chain-verified" : "is-chain-hold"} key={capaCaseId}>
                      <div>
                        <StatusBadge tone={chainVerified ? "success" : statusMeta.tone} compact>
                          {chainVerified
                            ? "CHAIN VERIFIED"
                            : state?.status === "VERIFIED" && !bindingMatches
                              ? "CONTRACT_HOLD"
                              : state?.status === "VERIFIED" && !projectionVerified
                                ? "CAPA VERIFIED · REVIEW STALE"
                                : `${status}${stale ? " · STALE" : ""}`}
                        </StatusBadge>
                        <button type="button" onClick={() => retryCapa(capaCaseId)} disabled={capaLoadingIds.includes(capaCaseId)}>
                          {capaLoadingIds.includes(capaCaseId) ? <LoaderCircle className="is-spinning" size={12} /> : <RefreshCw size={12} />}
                          GET 对账
                        </button>
                      </div>
                      <strong>{capaCaseId}</strong>
                      {capa ? (
                        <>
                          <small>{state?.status === "VERIFIED" ? capa.status : `STALE · ${capa.status}`} · plan {capa.selection.plan.plan_id}</small>
                          <p>{capa.initial_queue.open_count} open / {capa.final_queue?.closed_count ?? 0} verified closed</p>
                          {state?.status === "VERIFIED" && !bindingMatches ? (
                            <p>Review link 与 CAPA GET 摘要未形成同一绑定；刷新 Review Projection 后再判断。</p>
                          ) : null}
                          {errorDetail(state) ? <p>{errorDetail(state)}</p> : null}
                          {capa.execution ? (
                            <Link to={`/lineage?task=${encodeURIComponent(capa.execution.child_task_id)}`}>
                              <Link2 size={12} /> Child Task · {compact(capa.execution.child_task_id)}
                            </Link>
                          ) : <em>Child Task · NOT_CREATED</em>}
                          <code>{compact(capa.execution?.child_lineage_report_sha256 ?? link?.child_lineage_report_sha256)}</code>
                        </>
                      ) : (
                        <p>{errorDetail(state) || statusMeta.detail}</p>
                      )}
                      <Link to={`/capa?layer=controlled&task=${encodeURIComponent(taskId)}&case=${encodeURIComponent(capaCaseId)}`}>
                        打开 CAPA 账本 <ArrowRight size={12} />
                      </Link>
                    </article>
                  );
                }) : <EmptyFact>具名决定尚未关联 CAPA；深链状态为 NOT_CREATED。</EmptyFact>}
              </section>
            </div>

            <div className="incident-review-task-lineage">
              <header>
                <strong>TASK LINEAGE</strong>
                <code>{compact(projection.task_lineage_report_sha256)}</code>
              </header>
              <div>
                {projection.task_lineage_nodes.map((node) => (
                  <article key={node.task_id}>
                    <span>D{node.depth}</span>
                    <div>
                      <strong>{node.task_id}</strong>
                      <small>parent · {node.parent_task_id ?? "ROOT"}</small>
                    </div>
                    <StatusBadge tone={!projectionVerified ? "warning" : domainTone(node.execution_status)} compact>
                      {!projectionVerified ? "STALE" : node.execution_status}
                    </StatusBadge>
                    <code>{compact(node.evidence_sha256)}</code>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <footer className="incident-review-projection__footer">
            <div>
              <Digest label="REVIEW PROJECTION SHA-256" value={projection.projection_sha256} />
              <Digest label="CONTROL PLANE BUNDLE SHA-256" value={projection.control_plane_bundle_sha256} />
              <Digest label="DECISION PACKET SHA-256" value={projection.contrastive_decision_packet_sha256} />
            </div>
            <p><ShieldCheck size={14} />{projection.claim_boundary}</p>
            <strong>CAPA 写入结果未知时，本组件只允许显式 GET 对账；不会自动重放任何写请求。</strong>
          </footer>
        </>
      ) : (
        <div className="incident-review-no-projection">
          <AlertTriangle size={24} />
          <div>
            <strong>{statusCopy.title}</strong>
            <p>{statusCopy.detail}</p>
            <small>当前页面不会用 Incident 原始字段、fixture 或上一次 PASS 补齐缺失投影。</small>
          </div>
          <button type="button" onClick={() => void refreshProjection()} disabled={loading}>
            <RefreshCw size={14} /> 重试只读 GET
          </button>
        </div>
      )}
    </section>
  );
}
