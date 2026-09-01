import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  FileCheck2,
  GitBranch,
  LoaderCircle,
  LockKeyhole,
  Play,
  RefreshCcw,
  ShieldCheck,
  Split,
  UserCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { AgentTask } from "../agentDomain";
import type {
  CapaOutcomeAssessment,
  ControlledCapaCase,
  GovernedOutcomeEnvelope,
  IndustrialDeliveryReceipt,
  IndustrialRemediationPlan,
} from "../capaDomain";
import { useProduct } from "../ProductContext";
import { OperatorApiError, operatorActorUserId, listAgentTasks } from "../data/api";
import {
  approveControlledCapaCase,
  executeControlledCapaCase,
  getCapaOutcomeAssessment,
  getGovernedOutcomeEnvelope,
  getIndustrialDelivery,
  listControlledCapaCases,
  selectControlledCapaPlan,
} from "../data/capaApi";
import { ActionButton, Modal, Panel, StatusBadge } from "./ui";
import "../styles/capa-delivery.css";

interface ScopedCapaCase {
  task: AgentTask;
  capa: ControlledCapaCase;
}

interface ScopedDelivery {
  task: AgentTask;
  delivery: IndustrialDeliveryReceipt;
  canCreateCapa: boolean;
}

type CapaDialog =
  | {
      kind: "CREATE";
      delivery: ScopedDelivery;
      plan: IndustrialRemediationPlan;
      idempotencyKey: string;
    }
  | { kind: "APPROVE" | "EXECUTE"; entry: ScopedCapaCase };

function shortDigest(value: string | undefined | null): string {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "—";
}

function capaTone(status: ControlledCapaCase["status"]) {
  if (status === "RECOVERED_TO_HUMAN_REVIEW") return "success" as const;
  if (status === "STILL_BLOCKED" || status === "TRANSFERRED_TO_INVESTIGATION") return "danger" as const;
  if (status === "SELECTED") return "warning" as const;
  if (status === "APPROVED" || status === "DERIVED_VERSION_READY") return "info" as const;
  return "neutral" as const;
}

function strategyLabel(strategy: IndustrialRemediationPlan["strategy"]): string {
  if (strategy === "containment_first") return "先隔离风险";
  if (strategy === "actionable_recovery") return "优先恢复可执行项";
  return "完整证据闭环";
}

function outcomeTone(status: CapaOutcomeAssessment["release_feasibility_status"]) {
  return status === "OBSERVED_RECOVERY_TO_HUMAN_REVIEW" ? "success" as const : "warning" as const;
}

function isUnknownMutationOutcome(value: unknown): boolean {
  if (value instanceof OperatorApiError) {
    return value.code === "REQUEST_TIMEOUT" || value.status === 0;
  }
  // Once a write was dispatched, any client-side transport/decoding exception is
  // non-authoritative: the service may already have committed the command.
  return true;
}

function unknownMutationNotice(kind: CapaDialog["kind"]): string {
  const operation = kind === "CREATE" ? "创建 CAPA" : kind === "APPROVE" ? "批准 CAPA" : "执行 CAPA";
  return `WRITE RESULT UNKNOWN / HOLD · ${operation}请求超时或连接中断，服务端可能已经接收。页面未将其记为失败，也不会自动重放；请先刷新当前 CAPA 账本对账。production_release_allowed=false。`;
}

export function ControlledCapaWorkbench() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const requestedCaseId = searchParams.get("case")?.trim() ?? "";
  const { activeWorkspace, activeProject, connection } = useProduct();
  const [entries, setEntries] = useState<ScopedCapaCase[]>([]);
  const [deliveries, setDeliveries] = useState<ScopedDelivery[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [selectedDeliveryTaskId, setSelectedDeliveryTaskId] = useState("");
  const [loading, setLoading] = useState(false);
  const [partialFailureCount, setPartialFailureCount] = useState(0);
  const [deliveryFailureCount, setDeliveryFailureCount] = useState(0);
  const [focusNotice, setFocusNotice] = useState<string>();
  const [error, setError] = useState<string>();
  const [dialog, setDialog] = useState<CapaDialog>();
  const [actorName, setActorName] = useState("");
  const [note, setNote] = useState("");
  const [attested, setAttested] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [outcome, setOutcome] = useState<CapaOutcomeAssessment>();
  const [outcomeEnvelope, setOutcomeEnvelope] = useState<GovernedOutcomeEnvelope>();
  const [outcomeState, setOutcomeState] = useState<"IDLE" | "LOADING" | "VERIFIED" | "ASSESSMENT_VERIFIED" | "UNAVAILABLE">("IDLE");
  const requestRef = useRef(0);
  const mutationRequestRef = useRef(0);
  const scopeKey = `${activeWorkspace?.workspace_id ?? ""}::${activeProject?.project_id ?? ""}`;
  const scopeIdentityRef = useRef({ key: scopeKey, generation: 0 });
  if (scopeIdentityRef.current.key !== scopeKey) {
    scopeIdentityRef.current = {
      key: scopeKey,
      generation: scopeIdentityRef.current.generation + 1,
    };
    requestRef.current += 1;
    mutationRequestRef.current += 1;
  }

  const refresh = useCallback(async () => {
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    const generation = ++requestRef.current;
    const scopeGeneration = scopeIdentityRef.current.generation;
    const requestIsCurrent = () => (
      generation === requestRef.current &&
      scopeGeneration === scopeIdentityRef.current.generation &&
      scopeKey === scopeIdentityRef.current.key
    );
    setError(undefined);
    setFocusNotice(undefined);
    setPartialFailureCount(0);
    setDeliveryFailureCount(0);
    if (!workspaceId || !projectId || connection.api !== "CONNECTED") {
      setEntries([]);
      setDeliveries([]);
      setSelectedKey("");
      setSelectedDeliveryTaskId("");
      return;
    }
    setLoading(true);
    try {
      const tasks = await listAgentTasks(workspaceId, projectId);
      const next: ScopedCapaCase[] = [];
      const nextDeliveries: ScopedDelivery[] = [];
      let failed = 0;
      let failedDeliveries = 0;
      for (let offset = 0; offset < tasks.length; offset += 12) {
        const chunk = tasks.slice(offset, offset + 12);
        const caseResults = await Promise.allSettled(
          chunk.map(async (task) => ({ task, cases: await listControlledCapaCases(task.task_id) })),
        );
        const completed = chunk.filter((task) => task.execution_status === "COMPLETED");
        const deliveryResults = await Promise.allSettled(
          completed.map(async (task) => ({
            task,
            delivery: await getIndustrialDelivery(task.task_id),
          })),
        );
        if (!requestIsCurrent()) return;
        caseResults.forEach((result) => {
          if (result.status === "rejected") {
            failed += 1;
            return;
          }
          result.value.cases.forEach((capa) => next.push({ task: result.value.task, capa }));
        });
        deliveryResults.forEach((result) => {
          if (result.status === "rejected") {
            failedDeliveries += 1;
            return;
          }
          nextDeliveries.push({
            ...result.value,
            canCreateCapa: result.value.task.source_kind === "local_authorized_directory",
          });
        });
      }
      next.sort((a, b) => b.capa.selection.created_at.localeCompare(a.capa.selection.created_at));
      nextDeliveries.sort((a, b) => b.task.updated_at.localeCompare(a.task.updated_at));
      if (!requestIsCurrent()) return;
      setEntries(next);
      setDeliveries(nextDeliveries);
      setPartialFailureCount(failed);
      setDeliveryFailureCount(failedDeliveries);
      const requested = next.find((entry) => {
        const matchesTask = !requestedTaskId || [
          entry.task.task_id,
          entry.capa.parent_task_id,
          entry.capa.execution?.child_task_id,
          entry.capa.recovery?.child_task_id,
        ].some((taskId) => taskId === requestedTaskId);
        return matchesTask && (!requestedCaseId || entry.capa.case_id === requestedCaseId);
      });
      const requestedDelivery = !requestedCaseId
        ? nextDeliveries.find((entry) => entry.task.task_id === requestedTaskId)
        : undefined;
      if ((requestedTaskId || requestedCaseId) && !requested && !requestedDelivery) {
        setFocusNotice("深链接 CAPA 不属于当前 workspace / project，已拒绝定位。");
      } else if (
        requestedTaskId &&
        requested &&
        requested.task.task_id !== requestedTaskId
      ) {
        setFocusNotice(
          `已从 Child Run ${shortDigest(requestedTaskId)} 回溯到 Parent Task ${shortDigest(requested.task.task_id)}，并定位 CAPA ${shortDigest(requested.capa.case_id)}。`,
        );
      }
      setSelectedKey((current) => {
        if (requested) return requested.capa.case_id;
        if (requestedDelivery) return "";
        if (next.some((entry) => entry.capa.case_id === current)) return current;
        return next[0]?.capa.case_id ?? "";
      });
      setSelectedDeliveryTaskId((current) => {
        if (requested) return requested.task.task_id;
        if (requestedDelivery) return requestedDelivery.task.task_id;
        if (nextDeliveries.some((entry) => entry.task.task_id === current)) return current;
        return next[0]?.task.task_id ?? nextDeliveries[0]?.task.task_id ?? "";
      });
    } catch (caught) {
      if (requestIsCurrent()) {
        setEntries([]);
        setDeliveries([]);
        setError(caught instanceof Error ? caught.message : "无法读取受控 CAPA 案件");
      }
    } finally {
      if (requestIsCurrent()) setLoading(false);
    }
  }, [activeProject?.project_id, activeWorkspace?.workspace_id, connection.api, requestedCaseId, requestedTaskId, scopeKey]);

  useEffect(() => {
    setEntries([]);
    setDeliveries([]);
    setSelectedKey("");
    setSelectedDeliveryTaskId("");
    setDialog(undefined);
    mutationRequestRef.current += 1;
    setMutating(false);
    void refresh();
  }, [refresh]);

  const selected = useMemo(
    () => entries.find((entry) => entry.capa.case_id === selectedKey),
    [entries, selectedKey],
  );

  const selectedDelivery = useMemo(
    () => deliveries.find((entry) => entry.task.task_id === (selected?.task.task_id ?? selectedDeliveryTaskId)),
    [deliveries, selected?.task.task_id, selectedDeliveryTaskId],
  );

  useEffect(() => {
    let cancelled = false;
    const outcomeScopeGeneration = scopeIdentityRef.current.generation;
    const outcomeScopeKey = scopeKey;
    const outcomeIsCurrent = () => (
      !cancelled &&
      outcomeScopeGeneration === scopeIdentityRef.current.generation &&
      outcomeScopeKey === scopeIdentityRef.current.key
    );
    setOutcome(undefined);
    setOutcomeEnvelope(undefined);
    if (!selected?.capa.recovery) {
      setOutcomeState("IDLE");
      return () => { cancelled = true; };
    }
    setOutcomeState("LOADING");
    void Promise.allSettled([
      getCapaOutcomeAssessment(selected.task.task_id, selected.capa.case_id),
      getGovernedOutcomeEnvelope(selected.task.task_id, selected.capa.case_id),
    ]).then(([assessmentResult, envelopeResult]) => {
      if (!outcomeIsCurrent()) return;
      if (assessmentResult.status === "rejected") {
        setOutcomeState("UNAVAILABLE");
        return;
      }
      const assessment = assessmentResult.value;
      setOutcome(assessment);
      if (envelopeResult.status === "rejected") {
        setOutcomeState("ASSESSMENT_VERIFIED");
        return;
      }
      const envelope = envelopeResult.value;
      if (
        assessment.child_task_id !== envelope.subject.child_task_id ||
        assessment.parent_task_id !== envelope.subject.parent_task_id
      ) {
        setOutcomeState("UNAVAILABLE");
        return;
      }
      setOutcome(assessment);
      setOutcomeEnvelope(envelope);
      setOutcomeState("VERIFIED");
    }).catch(() => {
      if (outcomeIsCurrent()) setOutcomeState("UNAVAILABLE");
    });
    return () => { cancelled = true; };
  }, [scopeKey, selected?.capa.case_id, selected?.capa.recovery, selected?.task.task_id]);

  const openDialog = (kind: "APPROVE" | "EXECUTE", entry: ScopedCapaCase) => {
    setDialog({ kind, entry });
    const existingAuthorization = kind === "EXECUTE" ? entry.capa.execution_authorization : undefined;
    setActorName(existingAuthorization?.reviewer_identity ?? "");
    setNote(existingAuthorization?.execution_note ?? "");
    setAttested(false);
    setError(undefined);
  };

  const openCreateDialog = (delivery: ScopedDelivery, plan: IndustrialRemediationPlan) => {
    setDialog({
      kind: "CREATE",
      delivery,
      plan,
      idempotencyKey: `web-capa:${delivery.task.task_id}:${plan.plan_id}:${crypto.randomUUID()}`,
    });
    setActorName("");
    setNote("");
    setAttested(false);
    setError(undefined);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!dialog || !attested || actorName.trim().length < 2 || mutating) return;
    if (note.trim().length < 2) return;
    const submittedDialog = dialog;
    const mutationGeneration = ++mutationRequestRef.current;
    const mutationScopeGeneration = scopeIdentityRef.current.generation;
    const mutationScopeKey = scopeKey;
    const mutationIsCurrent = () => (
      mutationGeneration === mutationRequestRef.current &&
      mutationScopeGeneration === scopeIdentityRef.current.generation &&
      mutationScopeKey === scopeIdentityRef.current.key
    );
    setMutating(true);
    setError(undefined);
    setFocusNotice(undefined);
    try {
      if (submittedDialog.kind === "CREATE") {
        const created = await selectControlledCapaPlan({
          taskId: submittedDialog.delivery.task.task_id,
          planId: submittedDialog.plan.plan_id,
          planSha256: submittedDialog.plan.plan_sha256,
          note: `[具名选择人 ${actorName.trim()}; account=${operatorActorUserId}] ${note.trim()}`,
          idempotencyKey: submittedDialog.idempotencyKey,
        });
        if (!mutationIsCurrent()) return;
        const scoped = { task: submittedDialog.delivery.task, capa: created };
        setEntries((current) => [scoped, ...current.filter((entry) => entry.capa.case_id !== created.case_id)]);
        setSelectedKey(created.case_id);
        setSelectedDeliveryTaskId(submittedDialog.delivery.task.task_id);
        setDialog(undefined);
        return;
      }
      const { task, capa } = submittedDialog.entry;
      const updated = submittedDialog.kind === "APPROVE"
        ? await approveControlledCapaCase(
            task.task_id,
            capa.case_id,
            `[具名复核人 ${actorName.trim()}; account=${operatorActorUserId}] ${note.trim()}`,
            capa.selection.plan.selected_work_order_ids,
          )
        : await executeControlledCapaCase(
            task.task_id,
            capa.case_id,
            actorName.trim(),
            note.trim(),
            capa.approval?.binding_sha256 ?? "",
          );
      if (!mutationIsCurrent()) return;
      setEntries((current) => current.map((entry) => (
        entry.capa.case_id === updated.case_id ? { ...entry, capa: updated } : entry
      )));
      setDialog(undefined);
    } catch (caught) {
      if (!mutationIsCurrent()) return;
      if (isUnknownMutationOutcome(caught)) {
        setDialog(undefined);
        setAttested(false);
        setFocusNotice(unknownMutationNotice(submittedDialog.kind));
      } else {
        setError(caught instanceof Error ? caught.message : "受控 CAPA 操作失败");
      }
    } finally {
      if (mutationIsCurrent()) setMutating(false);
    }
  };

  const dialogPlan = dialog
    ? dialog.kind === "CREATE" ? dialog.plan : dialog.entry.capa.selection.plan
    : undefined;
  const dialogResourceId = dialog
    ? dialog.kind === "CREATE" ? dialog.delivery.task.task_id : dialog.entry.capa.case_id
    : "";

  if (!activeWorkspace || !activeProject) {
    return <div className="controlled-capa-empty"><LockKeyhole size={22} /><strong>先选择真实项目</strong><p>受控 CAPA 必须绑定 workspace、project 与 parent task。</p></div>;
  }

  return (
    <div className="controlled-capa-workbench">
      <header className="controlled-capa-toolbar">
        <div>
          <span>PRODUCT SERVICE · DERIVED COPY ONLY</span>
          <strong>受控 CAPA 案件</strong>
          <small>Parent Task → 具名批准 → 派生副本 → Child Run → 人工复核</small>
        </div>
        <ActionButton variant="secondary" icon={RefreshCcw} onClick={() => void refresh()} disabled={loading}>刷新</ActionButton>
      </header>

      {error ? <div className="controlled-capa-error"><AlertTriangle size={14} />{error}</div> : null}
      {focusNotice ? <div className="controlled-capa-warning">{focusNotice}</div> : null}
      {partialFailureCount > 0 ? <div className="controlled-capa-warning">{partialFailureCount} 个 Task 的 CAPA 只读视图不可用；未用 fixture 补位。</div> : null}
      {deliveryFailureCount > 0 ? <div className="controlled-capa-warning">{deliveryFailureCount} 个已完成 Task 尚无可核验 Industrial Delivery；对应方案入口保持不可用。</div> : null}

      <div className="controlled-capa-grid">
        <Panel className="controlled-capa-inbox" variant="subtle">
          <header><span>DELIVERY / CASE INBOX</span><em>{deliveries.length + entries.length}</em></header>
          <div>
            {loading && entries.length === 0 && deliveries.length === 0 ? <div className="controlled-capa-empty"><LoaderCircle className="is-spinning" size={18} />正在对账工业交付与 CAPA 账本…</div> : null}
            {!loading && entries.length === 0 && deliveries.length === 0 ? (
              <div className="controlled-capa-empty">
                <GitBranch size={21} />
                <strong>当前项目没有 SHA VERIFIED 交付或 CAPA Case</strong>
                <p>完成真实 Product Task 后，Industrial Delivery 会先在这里出现；具名选择方案后才生成 CAPA。</p>
                <button type="button" onClick={() => navigate("/command-center")}>前往 Agent Task <ArrowRight size={13} /></button>
              </div>
            ) : null}
            {deliveries.length > 0 ? <p className="controlled-capa-inbox-label">INDUSTRIAL DELIVERY · READ ONLY</p> : null}
            {deliveries.map((entry) => (
              <button
                type="button"
                className={!selectedKey && entry.task.task_id === selectedDeliveryTaskId ? "is-active is-delivery" : "is-delivery"}
                onClick={() => {
                  setFocusNotice(undefined);
                  setSelectedKey("");
                  setSelectedDeliveryTaskId(entry.task.task_id);
                }}
                key={`delivery-${entry.task.task_id}`}
              >
                <span className="controlled-capa-state is-info" />
                <div><strong>{entry.delivery.industrial_task}</strong><small>{entry.task.task_id}</small><p>{entry.delivery.final_decision} · {entry.delivery.remediation_plans.length} candidate plans</p></div>
                <StatusBadge tone={entry.canCreateCapa ? "info" : "locked"} compact>{entry.canCreateCapa ? "SELECTABLE" : "READ ONLY"}</StatusBadge>
              </button>
            ))}
            {entries.length > 0 ? <p className="controlled-capa-inbox-label">CONTROLLED CAPA · PERSISTED</p> : null}
            {entries.map((entry) => (
              <button type="button" className={entry.capa.case_id === selectedKey ? "is-active" : ""} onClick={() => { setFocusNotice(undefined); setSelectedDeliveryTaskId(entry.task.task_id); setSelectedKey(entry.capa.case_id); }} key={entry.capa.case_id}>
                <span className={`controlled-capa-state is-${capaTone(entry.capa.status)}`} />
                <div><strong>{entry.capa.selection.plan.title}</strong><small>{entry.capa.case_id}</small><p>{entry.capa.status} · task {entry.task.task_id}</p></div>
                <StatusBadge tone={capaTone(entry.capa.status)} compact>{entry.capa.status}</StatusBadge>
              </button>
            ))}
          </div>
        </Panel>

        <main className="controlled-capa-main">
          {!selected && selectedDelivery ? (
            <>
              <header className="controlled-capa-case-head">
                <div>
                  <span>INDUSTRIAL DELIVERY · {selectedDelivery.task.task_id}</span>
                  <h2>{selectedDelivery.delivery.industrial_task}</h2>
                  <p>{selectedDelivery.delivery.decision_reason}</p>
                </div>
                <StatusBadge tone={selectedDelivery.delivery.final_decision === "PASS" ? "success" : "warning"}>{selectedDelivery.delivery.final_decision}</StatusBadge>
              </header>

              <div className="controlled-capa-delivery-boundary">
                <FileCheck2 size={15} />
                <p>这里读取 ProductService 的 Industrial Delivery；浏览器已按 canonical JSON 重算 SHA-256，并核对 Header 与 ETag。Agent 只生成确定性方案；选择、批准、执行和生产放行权仍归具名人员。</p>
                <code>{selectedDelivery.delivery.schema_version}</code>
              </div>

              <div className="controlled-capa-delivery-metrics">
                <span><strong>{selectedDelivery.delivery.multi_source_fusion.length}</strong><small>证据来源</small></span>
                <span><strong>{selectedDelivery.delivery.evidence_fusion_matrix.length}</strong><small>融合条目</small></span>
                <span><strong>{selectedDelivery.delivery.risk_clusters.length}</strong><small>风险簇</small></span>
                <span><strong>{selectedDelivery.delivery.executable_work_orders.length}</strong><small>原子工单</small></span>
              </div>

              <section className="controlled-capa-evidence-fusion">
                <header><span><Database size={12} /> SIX-SOURCE EVIDENCE</span><small>ROOT CAUSE NOT ESTABLISHED</small></header>
                <div>
                  {selectedDelivery.delivery.multi_source_fusion.map((source) => (
                    <article key={`${source.source_type}-${source.evidence_ref}`}>
                      <span>{source.source_type}</span>
                      <strong>{source.observed_count}</strong>
                      <p>{source.role_in_decision}</p>
                      <code>{shortDigest(source.evidence_sha256)}</code>
                    </article>
                  ))}
                </div>
              </section>

              <section className="controlled-capa-risk-clusters">
                <header><span><Split size={12} /> RISK CLUSTERS</span><small>OPERATIONAL AGGREGATION ONLY</small></header>
                <div>
                  {selectedDelivery.delivery.risk_clusters.length === 0 ? <p className="controlled-capa-inline-empty">当前回执没有风险簇；未从工单推断补画。</p> : null}
                  {selectedDelivery.delivery.risk_clusters.map((cluster) => (
                    <article key={cluster.risk_cluster_id}>
                      <div><strong>{cluster.title}</strong><p>{cluster.objective}</p></div>
                      <dl><div><dt>samples</dt><dd>{cluster.affected_sample_count}</dd></div><div><dt>work orders</dt><dd>{cluster.atomic_work_order_count}</dd></div><div><dt>owner</dt><dd>{cluster.human_owner_role}</dd></div></dl>
                      <small>{cluster.reason_codes.join(" · ")} · machine action false</small>
                    </article>
                  ))}
                </div>
              </section>

              <section className="controlled-capa-plan-compare">
                <header><span>CANDIDATE REMEDIATION PLANS</span><small>{selectedDelivery.delivery.remediation_plans.length} SERVER-SEALED OPTIONS</small></header>
                <div>
                  {selectedDelivery.delivery.remediation_plans.map((plan) => (
                    <article key={plan.plan_id}>
                      <header><span>{strategyLabel(plan.strategy)}</span><code>{shortDigest(plan.plan_sha256)}</code></header>
                      <h3>{plan.title}</h3>
                      <p>{plan.objective}</p>
                      <dl><div><dt>证据覆盖</dt><dd>{Math.round(plan.evidence_coverage_ratio * 100)}%</dd></div><div><dt>相对 effort</dt><dd>{plan.relative_effort_points}</dd></div><div><dt>执行 / 延后</dt><dd>{plan.selected_work_order_ids.length} / {plan.deferred_work_order_ids.length}</dd></div></dl>
                      <small>{plan.review_eligibility} · production release false</small>
                      <button type="button" disabled={!selectedDelivery.canCreateCapa} onClick={() => openCreateDialog(selectedDelivery, plan)}>
                        {selectedDelivery.canCreateCapa ? <>具名选择并创建 CAPA <ArrowRight size={13} /></> : <><LockKeyhole size={13} /> 仅授权本地来源可创建</>}
                      </button>
                    </article>
                  ))}
                </div>
              </section>
            </>
          ) : !selected ? (
            <div className="controlled-capa-empty"><GitBranch size={24} /><strong>选择一个受控 CAPA Case</strong><p>页面只展示后端已持久化的选择、批准、派生与复验事实。</p></div>
          ) : (
            <>
              <header className="controlled-capa-case-head">
                <div><span>{selected.capa.case_id}</span><h2>{selected.capa.selection.plan.title}</h2><p>{selected.capa.selection.plan.objective}</p></div>
                <StatusBadge tone={capaTone(selected.capa.status)}>{selected.capa.status}</StatusBadge>
              </header>
              <div className="controlled-capa-flow">
                {[
                  ["PLAN", true],
                  ["APPROVAL", Boolean(selected.capa.approval)],
                  ["DERIVED COPY", Boolean(selected.capa.derived_version)],
                  ["CHILD RUN", Boolean(selected.capa.execution)],
                  ["OUTCOME", Boolean(selected.capa.recovery)],
                ].map(([label, complete], index) => <span className={complete ? "is-complete" : ""} key={String(label)}><i>{complete ? <CheckCircle2 size={11} /> : index + 1}</i>{label}</span>)}
              </div>

              <section className="controlled-capa-plan">
                <header><span>SELECTED PLAN</span><code>{shortDigest(selected.capa.selection.plan.plan_sha256)}</code></header>
                <div className="controlled-capa-plan-metrics">
                  <span><strong>{Math.round(selected.capa.selection.plan.evidence_coverage_ratio * 100)}%</strong><small>证据覆盖</small></span>
                  <span><strong>{selected.capa.selection.plan.relative_effort_points}</strong><small>相对 effort</small></span>
                  <span><strong>{selected.capa.selection.plan.selected_work_order_ids.length}</strong><small>选中工单</small></span>
                  <span><strong>{selected.capa.selection.plan.deferred_work_order_ids.length}</strong><small>延后工单</small></span>
                </div>
                <p>{selected.capa.selection.plan.strategy} · same-contract child run required · production release false</p>
              </section>

              <section className="controlled-capa-queue">
                <header><span>RESPONSIBILITY QUEUE</span><small>{selected.capa.final_queue ? "FINAL" : "INITIAL"}</small></header>
                {(selected.capa.final_queue ?? selected.capa.initial_queue).items.map((item) => (
                  <article key={item.queue_item_id}>
                    <span>{item.selected ? <CheckCircle2 size={13} /> : <LockKeyhole size={13} />}</span>
                    <div><strong>{item.action}</strong><p>{item.owner_role} · {item.required_skill}</p><small>{item.work_order_id} · {item.status} · {item.status_reason}</small></div>
                    <StatusBadge tone={item.status === "VERIFIED_CLOSED" ? "success" : item.status.includes("BLOCKED") || item.status.includes("FAILED") ? "danger" : "warning"} compact>{item.status}</StatusBadge>
                  </article>
                ))}
              </section>

              {selected.capa.recovery ? (
                <section className="controlled-capa-outcome">
                  <header><span>CHILD RUN OUTCOME</span><StatusBadge tone={selected.capa.recovery.recovery_success ? "success" : "danger"} compact>{selected.capa.recovery.status}</StatusBadge></header>
                  <div>
                    <span><strong>{selected.capa.recovery.verified_closed_work_order_count}</strong><small>verified closed</small></span>
                    <span><strong>{selected.capa.recovery.remaining_work_order_count}</strong><small>remaining</small></span>
                    <span><strong>{selected.capa.recovery.child_verification?.regressed_count ?? "—"}</strong><small>regressed</small></span>
                  </div>
                  <p>{selected.capa.recovery.required_human_action}</p>
                  <small>production_release_allowed=false · {shortDigest(selected.capa.recovery.receipt_sha256)}</small>
                </section>
              ) : null}

              {selected.capa.recovery && outcomeState === "LOADING" ? (
                <section className="controlled-capa-outcome-authority is-loading"><LoaderCircle className="is-spinning" size={15} /><p>正在并发重算 Outcome Assessment SHA 与 Governed Outcome Root…</p></section>
              ) : null}
              {selected.capa.recovery && outcomeState === "UNAVAILABLE" ? (
                <section className="controlled-capa-outcome-authority is-unavailable"><AlertTriangle size={16} /><div><strong>OUTCOME AUTHORITY UNAVAILABLE / HOLD</strong><p>结果封套缺失、作用域不一致或 SHA Header 验证失败。页面不会从 CAPA 聚合字段补画 Outcome Root。</p></div></section>
              ) : null}
              {selected.capa.recovery && outcomeState === "ASSESSMENT_VERIFIED" && outcome ? (
                <section className="controlled-capa-outcome-authority is-unavailable"><AlertTriangle size={16} /><div><strong>CAPA ASSESSMENT SHA VERIFIED · GOVERNED OUTCOME HOLD</strong><p>CAPA 结果评估已完成浏览器 SHA 对账，但 Incident→具名决定→CAPA 权威绑定缺失或不可验证，因此不生成 Governed Outcome Root。直接创建的 CAPA 仍保留完整 Assessment 与 Child Run，不冒充 Goal3 权威封套。</p><small>{shortDigest(outcome.assessment_sha256)} · production_release_allowed=false</small></div></section>
              ) : null}
              {outcomeState === "VERIFIED" && outcome && outcomeEnvelope ? (
                <section className="controlled-capa-outcome-authority is-verified">
                  <header><span>GOVERNED OUTCOME · SHA VERIFIED</span><StatusBadge tone={outcomeTone(outcome.release_feasibility_status)} compact>{outcome.release_feasibility_status}</StatusBadge></header>
                  <div className="controlled-capa-outcome-root">
                    <div><small>Outcome Root · RFC 8785 JCS</small><code>{outcomeEnvelope.outcome_root.value}</code></div>
                    <StatusBadge tone={outcomeEnvelope.signature.status === "NOT_CONFIGURED" ? "warning" : "success"} compact>{outcomeEnvelope.signature.status ?? "UNKNOWN"}</StatusBadge>
                  </div>
                  <div className="controlled-capa-outcome-grid">
                    <span><strong>{outcome.plan_observations.filter((item) => item.execution_status === "EXECUTED").length}</strong><small>executed plan</small></span>
                    <span><strong>{outcome.plan_observations.filter((item) => item.execution_status === "NOT_EXECUTED").length}</strong><small>unexecuted plan</small></span>
                    <span><strong>{outcomeEnvelope.result.closed_responsibility_item_count}</strong><small>closed duties</small></span>
                    <span><strong>{outcomeEnvelope.result.open_responsibility_item_count}</strong><small>open duties</small></span>
                  </div>
                  <p>{outcome.required_next_action}</p>
                  <small>{outcomeEnvelope.artifacts.length} bound artifacts · human_only · machine_write_permitted=false · production_release_allowed=false</small>
                </section>
              ) : null}
            </>
          )}
        </main>

        <aside className="controlled-capa-actions">
          <header><UserCheck size={14} /><span>HUMAN GATE</span></header>
          {!selected && selectedDelivery ? (
            <>
              <div className="controlled-capa-boundary"><ShieldCheck size={15} /><p>当前只读取已完成 Task 的交付建议。选择方案会创建新 CAPA Case，但不会执行工单或改写源数据。</p></div>
              <dl>
                <div><dt>source</dt><dd>{selectedDelivery.task.source_kind}</dd></div>
                <div><dt>agent authority</dt><dd>{selectedDelivery.delivery.autonomy_level}</dd></div>
                <div><dt>human gate</dt><dd>{String(selectedDelivery.delivery.production_human_approval_required)}</dd></div>
                <div><dt>production approval</dt><dd>{selectedDelivery.delivery.production_approval_status}</dd></div>
              </dl>
              {!selectedDelivery.canCreateCapa ? <div className="controlled-capa-boundary is-hold"><LockKeyhole size={15} /><p>该 Task 不是授权本地来源。方案可以审阅，但 CAPA 写入口保持锁定。</p></div> : null}
            </>
          ) : !selected ? <div className="controlled-capa-empty"><p>选择交付或 Case 后显示受控动作。</p></div> : (
            <>
              <div className="controlled-capa-boundary"><ShieldCheck size={15} /><p>源数据只读。整改只允许落在私有派生副本；Child PASS 仍不构成生产放行。</p></div>
              {selected.capa.status === "SELECTED" ? <ActionButton icon={UserCheck} onClick={() => openDialog("APPROVE", selected)}>具名批准方案</ActionButton> : null}
              {selected.capa.status === "APPROVED" ? <ActionButton icon={Play} onClick={() => openDialog("EXECUTE", selected)}>执行派生副本与 Child Run</ActionButton> : null}
              {selected.capa.status === "DERIVED_VERSION_READY" ? <ActionButton icon={RefreshCcw} onClick={() => openDialog("EXECUTE", selected)}>核验派生回执并继续 Child Run</ActionButton> : null}
              {selected.capa.approval ? <dl><div><dt>approved by</dt><dd>{selected.capa.approval.approved_by}</dd></div><div><dt>binding</dt><dd>{shortDigest(selected.capa.approval.binding_sha256)}</dd></div></dl> : null}
              {selected.capa.derived_version ? <dl><div><dt>derived version</dt><dd>{selected.capa.derived_version.version_id}</dd></div><div><dt>parent mutated</dt><dd>false</dd></div><div><dt>rollback</dt><dd>{selected.capa.derived_version.rollback_strategy}</dd></div></dl> : null}
              {selected.capa.execution_authorization ? <dl><div><dt>executed by</dt><dd>{selected.capa.execution_authorization.reviewer_identity}</dd></div><div><dt>authorization</dt><dd>{shortDigest(selected.capa.execution_authorization.authorization_sha256)}</dd></div></dl> : null}
              {selected.capa.execution ? <button className="controlled-capa-link" type="button" onClick={() => navigate(`/lineage?task=${encodeURIComponent(selected.capa.execution?.child_task_id ?? selected.task.task_id)}`)}>查看 Parent / Child 血缘 <ArrowRight size={13} /></button> : null}
            </>
          )}
        </aside>
      </div>

      {dialog ? (
        <Modal title={dialog.kind === "CREATE" ? "具名选择整改方案" : dialog.kind === "APPROVE" ? "具名批准受控 CAPA" : dialog.entry.capa.status === "DERIVED_VERSION_READY" ? "核验并继续 Child Run" : "确认执行派生副本"} onClose={() => { if (!mutating) setDialog(undefined); }}>
          <form className="controlled-capa-signoff" onSubmit={(event) => void submit(event)}>
            <div className="controlled-capa-signoff__binding"><ShieldCheck size={18} /><div><strong>{dialogResourceId}</strong><small>{dialogPlan?.selected_work_order_ids.length ?? 0} work orders · {shortDigest(dialogPlan?.plan_sha256)}</small></div></div>
            <label><span>{dialog.kind === "CREATE" ? "方案选择人姓名 / 工号" : "复核人姓名 / 工号"}</span><input value={actorName} onChange={(event) => setActorName(event.target.value)} placeholder="例如 QA-017 李工" autoFocus required /></label>
            <label><span>{dialog.kind === "CREATE" ? "选择依据" : dialog.kind === "APPROVE" ? "批准依据" : "执行确认说明"}</span><textarea value={note} onChange={(event) => setNote(event.target.value)} rows={4} placeholder={dialog.kind === "CREATE" ? "说明为何选择该覆盖范围、相对 effort 与残余风险组合。" : dialog.kind === "APPROVE" ? "说明已核对的工单范围、派生副本边界和验收标准。" : "说明已复核当前批准绑定、来源未漂移和派生执行边界。"} required /></label>
            {dialog.kind === "EXECUTE" ? <div className="controlled-capa-execute-warning"><AlertTriangle size={15} />{dialog.entry.capa.status === "DERIVED_VERSION_READY" ? "将重新核验已发布派生版本的内嵌回执、私有 manifest、来源授权与 profile，再继续同合同 Child Run；不会重建或覆盖派生版本。" : "将创建私有派生版本、执行已批准动作并启动同合同 Child Run。"} 复核身份、说明与批准 SHA 会作为不可变执行授权落盘；账户为 {operatorActorUserId}。</div> : null}
            <label className={attested ? "controlled-capa-attest is-checked" : "controlled-capa-attest"}><input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} /><LockKeyhole size={15} /><span><strong>{dialog.kind === "CREATE" ? "我已对比候选方案并确认仅创建受控 Case" : "我已复核证据并确认只在派生副本上执行"}</strong><small>不修改 parent source，不允许 raw redistribution，不授予生产权限。</small></span></label>
            <footer><button type="button" onClick={() => setDialog(undefined)} disabled={mutating}>取消</button><button className="is-primary" type="submit" disabled={!attested || actorName.trim().length < 2 || note.trim().length < 2 || mutating}>{mutating ? <LoaderCircle className="is-spinning" size={14} /> : dialog.kind === "CREATE" ? <GitBranch size={14} /> : dialog.kind === "APPROVE" ? <UserCheck size={14} /> : <Play size={14} />}{mutating ? "正在写入受控账本…" : dialog.kind === "CREATE" ? "创建受控 CAPA" : dialog.kind === "APPROVE" ? "批准并锁定方案" : "确认执行"}</button></footer>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
