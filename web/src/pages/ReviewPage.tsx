import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  FileCheck2,
  GitBranch,
  Inbox,
  Images,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type {
  AgentCapaLineageRecord,
  AgentIntervention,
  AgentReleaseReadiness,
  AgentTask,
  AgentTaskEvent,
  AgentTaskLineageReport,
  IndustrialIncident,
} from "../agentDomain";
import {
  ActionButton,
  ClaimBoundary,
  DetailRow,
  Digest,
  EmptyState,
  EvidenceSourceBadge,
  Metric,
  Panel,
  PanelHeader,
  StatusBadge,
} from "../components/ui";
import {
  getAgentReleaseReadiness,
  getAgentTaskLineage,
  getProjectGovernanceEffectiveness,
  listAgentCapaLineageRecords,
  listAgentInterventions,
  listAgentTaskEvents,
  listAgentTasks,
  listIndustrialIncidentV5,
  listOperatorImages,
} from "../data/api";
import {
  TaskVisualEvidencePanel,
  type TaskVisualEvidenceSummary,
} from "../components/TaskVisualEvidencePanel";
import { ReviewInteractionBridge } from "../components/ReviewInteractionBridge";
import { IncidentReviewProjectionPanel } from "../components/IncidentReviewProjectionPanel";
import { ReviewSyntheticAssetProof } from "../components/ReviewSyntheticAssetProof";
import { EvaluationEvidencePanel } from "../components/EvaluationEvidencePanel";
import { SemifinalManifestEvidence } from "../components/SemifinalManifestEvidence";
import type {
  GovernanceRateMetric,
  ProjectGovernanceEffectivenessSummary,
} from "../governanceDomain";
import type { OperatorImageAsset } from "../operatorDomain";
import { useProduct } from "../ProductContext";

interface LiveReviewState {
  scopeKey?: string;
  task?: AgentTask;
  tasks: AgentTask[];
  events: AgentTaskEvent[];
  interventions: AgentIntervention[];
  readiness?: AgentReleaseReadiness;
  lineage?: AgentTaskLineageReport;
  assets: OperatorImageAsset[];
  incidents: IndustrialIncident[];
  incidentsPending: boolean;
  capas: AgentCapaLineageRecord[];
  capasPending: boolean;
  governanceSummary?: ProjectGovernanceEffectivenessSummary;
  governanceSummaryPending: boolean;
  governanceSummaryFailed: boolean;
  partialFailures: string[];
}

const emptyState: LiveReviewState = {
  tasks: [],
  events: [],
  interventions: [],
  assets: [],
  incidents: [],
  incidentsPending: false,
  capas: [],
  capasPending: false,
  governanceSummaryPending: false,
  governanceSummaryFailed: false,
  partialFailures: [],
};

type ReviewCheckpointState = "complete" | "active" | "blocked" | "pending";
type ReviewRefreshOutcome = "SUCCESS" | "PARTIAL" | "ERROR";

interface ReviewCheckpoint {
  id: string;
  label: string;
  detail: string;
  icon: LucideIcon;
  complete: boolean;
  blocked?: boolean;
  href: string;
}

function compactDigest(value: string | null | undefined): string {
  return value ? `${value.slice(0, 10)}…${value.slice(-7)}` : "UNAVAILABLE";
}

function formatRate(metric: GovernanceRateMetric | undefined): string {
  if (!metric || metric.status !== "MEASURED" || metric.value === null) {
    return metric?.status.replaceAll("_", " ") ?? "NOT MEASURED";
  }
  return `${(metric.value * 100).toFixed(2)}%`;
}

function rateCounts(metric: GovernanceRateMetric | undefined): string {
  if (!metric || metric.status !== "MEASURED") return "NOT MEASURED";
  return `${metric.numerator}/${metric.denominator}`;
}

function statusTone(value: string): "success" | "warning" | "danger" | "neutral" {
  if (["COMPLETED", "VERIFIED", "READY_FOR_HUMAN_REVIEW"].includes(value)) return "success";
  if (["FAILED", "BLOCKED_EVIDENCE_INTEGRITY", "BLOCKED_SOURCE_STALE"].includes(value)) return "danger";
  if (value.includes("BLOCKED") || value.includes("HOLD") || value === "RECAPTURE") return "warning";
  return "neutral";
}

function taskStatusHeadline(value: string | undefined): string {
  switch (value) {
    case "CREATED": return "任务已创建";
    case "PLANNED": return "计划已生成";
    case "RUNNING": return "工具执行中";
    case "VERIFYING": return "证据核验中";
    case "COMPLETED": return "任务执行完成";
    case "FAILED": return "任务执行失败";
    case "CANCELLED": return "任务已取消";
    case "ARCHIVED": return "任务已归档";
    default: return "尚未创建";
  }
}

function releaseStatusHeadline(value: string): string {
  switch (value) {
    case "READY_FOR_HUMAN_REVIEW": return "待具名人工复核";
    case "BLOCKED_GATE_DECISION": return "未放行 · 需整改";
    case "BLOCKED_SOURCE_STALE": return "未放行 · 来源过期";
    case "BLOCKED_EVIDENCE_INTEGRITY": return "未放行 · 证据失败";
    case "DEMO_ONLY": return "仅限演示验证";
    case "PASS": return "规则通过 · 待人工复核";
    case "RECAPTURE": return "未放行 · 需重新采集";
    case "HOLD": return "未放行 · 保持拦截";
    default: return value === "NOT EVALUATED" ? "尚未形成结论" : value;
  }
}

export function ReviewPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("task")?.trim() ?? "";
  const {
    connection,
    activeWorkspace,
    activeProject,
    refreshConnection,
    connectionRefreshing,
  } = useProduct();
  const [refreshToken, setRefreshToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [supplementalLoading, setSupplementalLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [liveState, setLive] = useState<LiveReviewState>(emptyState);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date>();
  const [lastRefreshDurationMs, setLastRefreshDurationMs] = useState<number>();
  const [lastRefreshOutcome, setLastRefreshOutcome] = useState<ReviewRefreshOutcome>();
  const [visualEvidenceSummary, setVisualEvidenceSummary] = useState<TaskVisualEvidenceSummary>();

  useEffect(() => {
    let active = true;
    if (
      connection.api !== "CONNECTED" ||
      !activeWorkspace ||
      !activeProject
    ) {
      setLoading(false);
      setSupplementalLoading(false);
      setError(undefined);
      setLive(emptyState);
      setLastUpdatedAt(undefined);
      setLastRefreshDurationMs(undefined);
      setLastRefreshOutcome(undefined);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    setSupplementalLoading(false);
    setError(undefined);
    setLastRefreshOutcome(undefined);
    const scopeKey = `${activeWorkspace.workspace_id}:${activeProject.project_id}:${requestedTaskId || "LATEST"}`;
    const requestStartedAt = performance.now();
    const finalizeRefresh = (refreshOutcome: ReviewRefreshOutcome) => {
      if (!active) return;
      setSupplementalLoading(false);
      setLastUpdatedAt(new Date());
      setLastRefreshDurationMs(Math.max(0, Math.round(performance.now() - requestStartedAt)));
      setLastRefreshOutcome((current) => current === "PARTIAL" ? "PARTIAL" : refreshOutcome);
    };
    const loadGovernanceSummary = () => {
      return getProjectGovernanceEffectiveness(activeProject.project_id)
        .then((summary) => {
          if (!active) return;
          setLive((current) => current.scopeKey === scopeKey
            ? {
                ...current,
                governanceSummary: summary,
                governanceSummaryPending: false,
                governanceSummaryFailed: false,
                partialFailures: current.partialFailures.filter(
                  (label) => label !== "项目级治理效果汇总",
                ),
              }
            : current);
        })
        .catch(() => {
          if (!active) return;
          setLastRefreshOutcome("PARTIAL");
          setLive((current) => current.scopeKey === scopeKey
            ? {
                ...current,
                governanceSummary: undefined,
                governanceSummaryPending: false,
                governanceSummaryFailed: true,
                partialFailures: current.partialFailures.includes("项目级治理效果汇总")
                  ? current.partialFailures
                  : [...current.partialFailures, "项目级治理效果汇总"],
              }
            : current);
        });
    };
    const loadTaskSupplements = (taskId: string) => {
      return Promise.allSettled([
        listIndustrialIncidentV5(taskId),
        listAgentCapaLineageRecords(taskId),
      ] as const).then(([incidentResult, capaResult]) => {
        if (!active) return;
        const supplementalFailures = [
          ...(incidentResult.status === "rejected" ? ["Incident v5/v6"] : []),
          ...(capaResult.status === "rejected" ? ["CAPA 血缘"] : []),
        ];
        if (supplementalFailures.length) setLastRefreshOutcome("PARTIAL");
        setLive((current) => {
          if (current.scopeKey !== scopeKey) return current;
          const retainedFailures = current.partialFailures.filter(
            (label) => label !== "Incident v5/v6" && label !== "CAPA 血缘",
          );
          return {
            ...current,
            incidents: incidentResult.status === "fulfilled" ? incidentResult.value : [],
            incidentsPending: false,
            capas: capaResult.status === "fulfilled" ? capaResult.value : [],
            capasPending: false,
            partialFailures: [...retainedFailures, ...supplementalFailures],
          };
        });
      });
    };
    void (async () => {
      let refreshOutcome: ReviewRefreshOutcome = "SUCCESS";
      let waitsForSupplemental = false;
      try {
        const baseResults = await Promise.allSettled([
          listAgentTasks(activeWorkspace.workspace_id, activeProject.project_id),
          listOperatorImages(activeWorkspace.workspace_id, activeProject.project_id),
        ] as const);
        if (!active) return;

        const ordered = baseResults[0].status === "fulfilled"
          ? [...baseResults[0].value].sort(
              (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
            )
          : [];
        const assets = baseResults[1].status === "fulfilled" ? baseResults[1].value : [];
        const baseLabels = ["任务索引", "图像资产"];
        const partialFailures = baseResults.flatMap((result, index) =>
          result.status === "rejected" ? [baseLabels[index] ?? `读取项 ${index + 1}`] : [],
        );
        const task = requestedTaskId
          ? ordered.find((item) => item.task_id === requestedTaskId)
          : ordered[0];
        if (requestedTaskId && !task && baseResults[0].status === "fulfilled") {
          partialFailures.push("指定 Task 不属于当前项目");
        }

        if (!task) {
          refreshOutcome = partialFailures.length ? "PARTIAL" : "SUCCESS";
          setLive({
            ...emptyState,
            scopeKey,
            tasks: ordered,
            assets,
            governanceSummaryPending: true,
            partialFailures,
          });
          waitsForSupplemental = true;
          setSupplementalLoading(true);
          void loadGovernanceSummary().finally(() => finalizeRefresh(refreshOutcome));
          return;
        }

        const [activityResults, readinessResults] = await Promise.all([
          Promise.allSettled([
            listAgentTaskEvents(task.task_id),
            listAgentInterventions(task.task_id),
          ] as const),
          task.execution_status === "COMPLETED"
            ? Promise.allSettled([getAgentReleaseReadiness(task.task_id)] as const)
            : Promise.resolve(undefined),
        ]);
        const readinessResult = readinessResults?.[0];
        const readiness = readinessResult?.status === "fulfilled"
          ? readinessResult.value
          : undefined;
        const lineageResult = readiness?.evidence_integrity === "VERIFIED"
          ? await Promise.allSettled([getAgentTaskLineage(task.task_id)]).then(([result]) => result)
          : undefined;
        if (!active) return;

        const activityLabels = ["运行事件", "人工介入账本"];
        activityResults.forEach((result, index) => {
          if (result.status === "rejected") {
            partialFailures.push(activityLabels[index] ?? `任务活动读取项 ${index + 1}`);
          }
        });
        if (readinessResult?.status === "rejected") partialFailures.push("发布就绪");
        if (lineageResult?.status === "rejected") partialFailures.push("任务血缘");
        refreshOutcome = partialFailures.length ? "PARTIAL" : "SUCCESS";
        setLive({
          scopeKey,
          task,
          tasks: ordered,
          assets,
          events: activityResults[0].status === "fulfilled" ? activityResults[0].value : [],
          interventions: activityResults[1].status === "fulfilled" ? activityResults[1].value : [],
          readiness,
          lineage: lineageResult?.status === "fulfilled" ? lineageResult.value : undefined,
          incidents: [],
          incidentsPending: task.execution_status === "COMPLETED",
          capas: [],
          capasPending: task.execution_status === "COMPLETED",
          governanceSummaryPending: true,
          governanceSummaryFailed: false,
          partialFailures,
        });
        waitsForSupplemental = true;
        setSupplementalLoading(true);
        const supplementalLoads: Promise<unknown>[] = [loadGovernanceSummary()];
        if (task.execution_status === "COMPLETED") {
          supplementalLoads.push(loadTaskSupplements(task.task_id));
        }
        void Promise.all(supplementalLoads).finally(() => finalizeRefresh(refreshOutcome));
      } catch (caught: unknown) {
        if (!active) return;
        refreshOutcome = "ERROR";
        setLive({ ...emptyState, scopeKey });
        setError(caught instanceof Error ? caught.message : "无法读取当前项目的评审证据");
      } finally {
        if (active) {
          setLoading(false);
          if (!waitsForSupplemental) finalizeRefresh(refreshOutcome);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [
    activeProject?.project_id,
    activeWorkspace?.workspace_id,
    connection.api,
    requestedTaskId,
    refreshToken,
  ]);

  const activeScopeKey = activeWorkspace && activeProject
    ? `${activeWorkspace.workspace_id}:${activeProject.project_id}:${requestedTaskId || "LATEST"}`
    : undefined;
  const scopeReady = Boolean(activeScopeKey && liveState.scopeKey === activeScopeKey);
  const live = scopeReady ? liveState : emptyState;
  const initialLoading = Boolean(
    connection.api === "CONNECTED"
      && activeWorkspace
      && activeProject
      && !scopeReady,
  );
  const taskStillRunning = Boolean(
    live.task
      && ["CREATED", "PLANNED", "RUNNING", "VERIFYING"].includes(live.task.execution_status),
  );
  const supplementalPending = Boolean(
    supplementalLoading ||
      live.governanceSummaryPending ||
      live.incidentsPending ||
      live.capasPending,
  );

  useEffect(() => {
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    const taskId = live.task?.task_id;
    if (!taskStillRunning || loading || connection.api !== "CONNECTED" || !workspaceId || !projectId || !taskId) return;
    let disposed = false;
    let timer: number | undefined;
    const pollCoreTaskState = async () => {
      try {
        const tasks = await listAgentTasks(workspaceId, projectId);
        if (disposed) return;
        const current = tasks.find((item) => item.task_id === taskId);
        if (
          current &&
          (current.updated_at !== live.task?.updated_at || current.execution_status !== live.task?.execution_status)
        ) {
          setRefreshToken((value) => value + 1);
          return;
        }
      } catch {
        // Background polling is best-effort; the visible manual refresh keeps explicit failure feedback.
      }
      if (!disposed) timer = window.setTimeout(() => void pollCoreTaskState(), 2_500);
    };
    timer = window.setTimeout(() => void pollCoreTaskState(), 2_500);
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [
    activeProject?.project_id,
    activeWorkspace?.workspace_id,
    connection.api,
    live.task?.execution_status,
    live.task?.task_id,
    live.task?.updated_at,
    loading,
    taskStillRunning,
  ]);

  const singleConfusionGroup =
    live.governanceSummary?.confusion_pooling_status === "SINGLE_UNIT"
      ? live.governanceSummary.confusion_groups[0]
      : undefined;
  const groupedConfusion =
    live.governanceSummary?.confusion_pooling_status === "GROUPED_BY_UNIT";

  const incident = [...live.incidents].sort(
    (left, right) => right.case_version - left.case_version,
  )[0];
  const taskHref = (path: string): string => live.task
    ? `${path}?task=${encodeURIComponent(live.task.task_id)}`
    : path;
  const capaHref = live.task
    ? `/capa?layer=controlled&task=${encodeURIComponent(live.task.task_id)}`
    : "/capa?layer=controlled";
  const evidenceHref = live.task
    ? `/evidence?task=${encodeURIComponent(live.task.task_id)}${
        incident
          ? `&case=${encodeURIComponent(incident.case_id)}&version=${incident.case_version}`
          : ""
      }`
    : "/evidence";
  const completedToolEvents = live.events.filter(
    (event) => event.stage.toLowerCase() === "tool" && event.status.toLowerCase() === "success",
  ).length;
  const eventPreview = [...live.events]
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-8);
  const source = connection.api === "CONNECTED" ? "LIVE_API" : "NOT_CONNECTED";
  const isSyntheticDemo = activeProject?.source_kind === "synthetic_demo";
  const inputScopeLabel = isSyntheticDemo ? "冻结演示输入" : "真实输入";
  const assetsUnavailable = live.partialFailures.includes("图像资产");
  const taskIndexUnavailable = live.partialFailures.includes("任务索引");
  const taskSelectionUnavailable = live.partialFailures.includes("指定 Task 不属于当前项目");
  const eventsUnavailable = live.partialFailures.includes("运行事件");
  const interventionsUnavailable = live.partialFailures.includes("人工介入账本");
  const incidentsUnavailable = live.partialFailures.includes("Incident v5/v6");
  const capasUnavailable = live.partialFailures.includes("CAPA 血缘");
  const blockingReadFailures = live.partialFailures.filter((label) => [
    "任务索引",
    "图像资产",
    "运行事件",
    "人工介入账本",
    "发布就绪",
    "任务血缘",
  ].includes(label));
  const humanReviewReceipt = [...live.interventions]
    .reverse()
    .find((item) => item.action === "acknowledge_result");
  const releaseBlocksHumanReview = Boolean(
    live.readiness
      && live.readiness.overall_status !== "READY_FOR_HUMAN_REVIEW",
  );
  const evidenceVerified = live.readiness?.evidence_integrity === "VERIFIED";
  const currentVisualSummary = !isSyntheticDemo && evidenceVerified
    && visualEvidenceSummary?.task_id === live.task?.task_id
    ? visualEvidenceSummary
    : undefined;
  const checkpoints: ReviewCheckpoint[] = [
    {
      id: "input",
      label: inputScopeLabel,
      detail: initialLoading
        ? "正在读取项目资产"
        : assetsUnavailable
        ? "资产索引读取失败"
        : isSyntheticDemo
          ? `${live.assets.length} 张冻结合成资产`
        : currentVisualSummary
          ? `${live.assets.length} 张工作簿 / ${currentVisualSummary.visual_count} 张任务冻结输入`
          : live.assets.length
          ? `${live.assets.length} 张当前工作簿图像`
          : "等待导入图像或数据集",
      icon: Images,
      complete: !assetsUnavailable && live.assets.length > 0,
      blocked: assetsUnavailable,
      href: "/workspace",
    },
    {
      id: "contract",
      label: "任务合同",
      detail: initialLoading
        ? "正在读取任务合同"
        : taskIndexUnavailable
        ? "Task 索引读取失败"
        : live.task
          ? live.task.execution_status
          : "等待创建受控 Task",
      icon: Workflow,
      complete: Boolean(live.task),
      blocked: taskIndexUnavailable,
      href: taskHref("/command-center"),
    },
    {
      id: "tools",
      label: "确定性执行",
      detail: initialLoading
        ? "正在读取工具事件"
        : eventsUnavailable
          ? "运行事件读取失败"
          : completedToolEvents
        ? `${completedToolEvents} 个成功 Tool 事件`
        : "尚无可审计工具事件",
      icon: Activity,
      complete: completedToolEvents > 0,
      blocked: eventsUnavailable,
      href: taskHref("/runs"),
    },
    {
      id: "evidence",
      label: "证据完整性",
      detail: initialLoading
        ? "正在核验回执"
        : taskStillRunning
          ? `${live.task?.execution_status} · 完成后核验`
          : live.readiness?.evidence_integrity ?? "NOT EVALUATED",
      icon: FileCheck2,
      complete: evidenceVerified,
      blocked: live.readiness?.evidence_integrity === "FAILED"
        || live.partialFailures.includes("发布就绪"),
      href: evidenceHref,
    },
    {
      id: "human-gate",
      label: "人工闸门",
      detail: initialLoading
        ? "正在读取人工边界"
        : interventionsUnavailable
          ? "人工介入账本读取失败"
          : humanReviewReceipt
            ? `具名审阅回执 #${humanReviewReceipt.sequence}`
            : live.readiness?.required_human_action ?? "等待任务结果",
      icon: BookOpenCheck,
      complete: Boolean(humanReviewReceipt),
      blocked: interventionsUnavailable || releaseBlocksHumanReview,
      href: capaHref,
    },
    {
      id: "delivery",
      label: "可验证交付",
      detail: initialLoading
        ? "正在读取血缘报告"
        : live.lineage
        ? humanReviewReceipt
          ? `${live.lineage.node_count} nodes / ${live.lineage.edge_count} edges`
          : `${live.lineage.node_count} nodes / ${live.lineage.edge_count} edges · 待人工终审`
        : "等待可验证血缘报告",
      icon: GitBranch,
      complete: Boolean(live.lineage && humanReviewReceipt),
      blocked: live.partialFailures.includes("任务血缘"),
      href: taskHref("/lineage"),
    },
  ];
  const firstIncompleteCheckpoint = checkpoints.findIndex((checkpoint) => !checkpoint.complete);
  const checkpointState = (
    checkpoint: ReviewCheckpoint,
    index: number,
  ): ReviewCheckpointState => {
    if (initialLoading) return "pending";
    if (checkpoint.complete) return "complete";
    if (checkpoint.blocked) return "blocked";
    if (index === firstIncompleteCheckpoint) return "active";
    return "pending";
  };
  const checkpointStateLabel = (
    checkpoint: ReviewCheckpoint,
    state: ReviewCheckpointState,
  ): string => {
    if (checkpoint.id === "human-gate") {
      if (state === "complete") return "具名复核可查";
      if (interventionsUnavailable) return "读取受阻";
      if (state === "blocked") return "先整改再复核";
      if (state === "active") return "等待具名复核";
    }
    if (state === "complete") return "证据可查";
    if (state === "blocked") return "读取受阻";
    if (state === "active") return "下一步";
    return "等待上游";
  };
  const refreshReview = () => {
    if (loading || supplementalPending || initialLoading || connection.api !== "CONNECTED") return;
    setLoading(true);
    setRefreshToken((value) => value + 1);
  };
  const selectReviewTask = (taskId: string) => {
    const next = new URLSearchParams(searchParams);
    if (taskId) next.set("task", taskId);
    else next.delete("task");
    setSearchParams(next, { replace: true });
  };
  const readinessUnavailable = live.partialFailures.includes("发布就绪");
  const latestDecision = live.task?.execution_status !== "COMPLETED"
    ? "NOT EVALUATED"
    : readinessUnavailable
      ? "UNAVAILABLE"
      : live.readiness?.overall_status ?? "UNAVAILABLE";

  let nextAction = {
    eyebrow: "NEXT VERIFIED STEP",
    title: "打开完整证据链",
    detail: "输入、任务、工具、证据和血缘均可下钻复核。",
    label: "查看完整血缘",
    icon: GitBranch,
    run: () => navigate(taskHref("/lineage")),
  };
  if (connection.api !== "CONNECTED") {
    nextAction = {
      eyebrow: "CONNECTION REQUIRED",
      title: "重新连接本地 API",
      detail: "评审路径不会用静态数据替代离线服务。",
      label: connectionRefreshing ? "正在检测 API…" : "重新检测 API",
      icon: RefreshCw,
      run: () => void refreshConnection(),
    };
  } else if (!activeProject || !activeWorkspace) {
    nextAction = {
      eyebrow: "PROJECT REQUIRED",
      title: "先选择一个项目",
      detail: "评审证据必须绑定工作空间和项目范围。",
      label: "前往图像工作簿",
      icon: Images,
      run: () => navigate("/workspace"),
    };
  } else if (initialLoading) {
    nextAction = {
      eyebrow: isSyntheticDemo ? "READING FROZEN DEMO EVIDENCE" : "READING LIVE EVIDENCE",
      title: "正在核对当前项目",
      detail: `等待${inputScopeLabel}、任务、回执和发布边界返回；不会显示上一个项目的数据。`,
      label: "正在读取证据…",
      icon: LoaderCircle,
      run: () => undefined,
    };
  } else if (taskSelectionUnavailable) {
    nextAction = {
      eyebrow: "TASK SCOPE MISMATCH",
      title: "指定 Task 不属于当前项目",
      detail: "已停止加载，避免把其他项目或已删除 Task 的证据混入当前评审。",
      label: "回到最新 Task",
      icon: RefreshCw,
      run: () => selectReviewTask(""),
    };
  } else if (error || blockingReadFailures.length) {
    nextAction = {
      eyebrow: "RECOVERABLE READ ERROR",
      title: "重试缺失的只读证据",
      detail: "已成功返回的证据继续保留，缺失项不会由 fixture 补位。",
      label: "重新读取证据",
      icon: RefreshCw,
      run: refreshReview,
    };
  } else if (live.assets.length === 0) {
    nextAction = {
      eyebrow: isSyntheticDemo ? "SAMPLE FIXTURE MISSING" : "01 · REAL INPUT",
      title: isSyntheticDemo ? "冻结演示资产缺失" : "导入真实图像或数据集",
      detail: isSyntheticDemo
        ? "隔离 Demo 不会用任意工作簿图片替代缺失 fixture。请重新准备演示根目录。"
        : "从真实输入开始，工作簿会计算本地像素指标并保留 SHA。",
      label: isSyntheticDemo ? "重新读取演示资产" : "打开导入工作区",
      icon: Images,
      run: isSyntheticDemo ? refreshReview : () => navigate("/workspace?import=1"),
    };
  } else if (!live.task) {
    nextAction = {
      eyebrow: "02 · TASK CONTRACT",
      title: "创建受控 Agent Task",
      detail: "把项目输入冻结为任务合同，再观察计划、工具调用和人工闸门。",
      label: "创建 Agent Task",
      icon: Workflow,
      run: () => navigate("/command-center?create=1"),
    };
  } else if (taskStillRunning) {
    nextAction = {
      eyebrow: "LIVE TASK · AUTO REFRESH",
      title: `${taskStatusHeadline(live.task.execution_status)}，页面持续更新`,
      detail: "只显示已落盘阶段事件；任务完成前不请求发布就绪或血缘结论。",
      label: "打开实时任务",
      icon: Activity,
      run: () => navigate(taskHref("/command-center")),
    };
  } else if (live.task.execution_status !== "COMPLETED") {
    nextAction = {
      eyebrow: "TASK NEEDS ATTENTION",
      title: taskStatusHeadline(live.task.execution_status),
      detail: "当前任务没有可用发布结论；打开任务查看错误、取消原因或重新创建合同。",
      label: "检查任务状态",
      icon: TriangleAlert,
      run: () => navigate(taskHref("/command-center")),
    };
  } else if (!completedToolEvents) {
    nextAction = {
      eyebrow: "03 · DETERMINISTIC EXECUTION",
      title: "进入任务并检查运行活动",
      detail: "评委应看到结构化阶段事件，而不是不可验证的思维链动画。",
      label: "打开当前任务",
      icon: Activity,
      run: () => navigate(taskHref("/command-center")),
    };
  } else if (!evidenceVerified) {
    nextAction = {
      eyebrow: "04 · EVIDENCE INTEGRITY",
      title: "核对工具回执与证据 SHA",
      detail: "完整性未验证时，血缘和发布结论保持不可用。",
      label: "检查证据清单",
      icon: FileCheck2,
      run: () => navigate(evidenceHref),
    };
  } else if (!live.lineage) {
    nextAction = {
      eyebrow: "05 · HUMAN GATE",
      title: "核对 CAPA 与人工决定",
      detail: "Agent 只提交建议，具名人工决定后才能形成可追溯复验。",
      label: "打开 CAPA 队列",
      icon: BookOpenCheck,
      run: () => navigate(capaHref),
    };
  } else if (live.readiness?.overall_status === "BLOCKED_GATE_DECISION") {
    nextAction = {
      eyebrow: "06 · CLOSE THE LOOP",
      title: live.readiness.open_work_order_count
        ? `${live.readiness.open_work_order_count} 张整改工单仍待闭环`
        : "门禁裁决仍未通过",
      detail: "由责任人完成整改、保留修改前后哈希，再按同一合同启动复验。",
      label: "打开 CAPA 责任队列",
      icon: BookOpenCheck,
      run: () => navigate(capaHref),
    };
  } else if (live.readiness?.overall_status === "BLOCKED_SOURCE_STALE") {
    nextAction = {
      eyebrow: "SOURCE AUTHORIZATION REQUIRED",
      title: "重新授权当前数据来源",
      detail: "来源已过期或不可用，旧任务结论不得沿用到新批次。",
      label: "检查来源授权",
      icon: LockKeyhole,
      run: () => navigate("/integrations"),
    };
  } else if (live.readiness?.overall_status === "DEMO_ONLY") {
    nextAction = {
      eyebrow: "REAL INPUT REQUIRED",
      title: "切换到已授权的真实项目输入",
      detail: "演示任务只能验证产品闭环，不能作为真实批次结论。",
      label: "导入真实数据",
      icon: Images,
      run: () => navigate("/workspace?import=1"),
    };
  } else if (live.readiness?.overall_status === "READY_FOR_HUMAN_REVIEW" && !humanReviewReceipt) {
    nextAction = {
      eyebrow: "HUMAN DECISION REQUIRED",
      title: "进入具名人工终审",
      detail: "规则已通过，但系统仍无生产放行权；由责任人独立确认或请求补证。",
      label: "打开人工终审",
      icon: BookOpenCheck,
      run: () => navigate(taskHref("/command-center")),
    };
  }
  const NextActionIcon = nextAction.icon;
  const nextActionDisabled = loading || initialLoading
    || (connection.api !== "CONNECTED" && connectionRefreshing);
  const openCheckpoint = (checkpoint: ReviewCheckpoint) => {
    if (
      checkpoint.id === "input"
      && live.task?.execution_status === "COMPLETED"
      && (isSyntheticDemo || evidenceVerified)
    ) {
      const target = document.getElementById("review-visual-proof");
      if (target) {
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
        target.focus({ preventScroll: true });
        return;
      }
    }
    navigate(checkpoint.href);
  };
  const workerSelection = incident?.worker_selection_receipt;
  const selectedWorkerEvidence = (workerSelection?.selected_worker_ids ?? []).map((workerId) => ({
    workerId,
    candidate: workerSelection?.candidates.find((candidate) => candidate.worker_id === workerId),
    receipt: incident?.worker_receipts.find((receipt) => receipt.worker_role === workerId),
  }));
  const rejectedWorkerEvidence = (workerSelection?.ranking ?? [])
    .filter((entry) => !entry.selected)
    .slice(0, 2)
    .map((entry) => ({
      ...entry,
      candidate: workerSelection?.candidates.find((candidate) => candidate.worker_id === entry.worker_id),
    }));
  const openHypotheses = (incident?.planning_belief_ledger.snapshots ?? [])
    .filter((snapshot) => snapshot.source_hypothesis_status !== "REJECTED")
    .slice(0, 3);
  const observedFact = incident?.decision_summary.observed_facts[0]
    ?? (completedToolEvents
      ? `${completedToolEvents} 个确定性 Tool 事件成功落盘`
      : "尚无可引用的确定性事实");
  const alternativeSummary = incident?.decision_summary.alternatives_kept_open.slice(0, 2).join(" · ")
    || openHypotheses.map((snapshot) => snapshot.hypothesis_id).join(" · ")
    || "尚无可引用的竞争解释";
  const selectedWorkerSummary = selectedWorkerEvidence.length
    ? `${taskStillRunning ? "正在调度" : "已调度"} ${selectedWorkerEvidence.map((item) => item.workerId).join("、")}`
    : live.incidentsPending
      ? "正在读取 Worker Selection 回执"
      : "尚无可引用的 Worker Selection 回执";
  const plannerMode = incident?.autonomy_guard_receipt?.planner_mode
    ?? incident?.planning_mode
    ?? "NOT OBSERVED";
  const opcuaSourceMode = incident?.request.opcua_snapshot.source_mode
    ?? (live.incidentsPending ? "READING" : incidentsUnavailable ? "UNAVAILABLE" : "NOT OBSERVED");
  const focusStageReady = Boolean(
    live.task
      && (isSyntheticDemo || evidenceVerified)
      && activeWorkspace
      && activeProject,
  );
  const openReleaseTruth = () => {
    const target = document.getElementById("review-release-truth");
    if (!target) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  };

  return (
    <div className="page-stack review-page" aria-busy={loading || supplementalPending}>
      <div className="review-lock-banner system-hub-toolbar">
        <LockKeyhole size={17} />
        <strong>REVIEWER MODE · READ ONLY</strong>
        <span>只读取当前项目账本；批准、执行、上传与生产放行全部禁用</span>
        <span className="review-refresh-state" role="status" aria-live="polite">
          {loading
            ? (scopeReady ? "正在刷新最新回执…" : "正在读取当前项目…")
            : supplementalPending
              ? "核心证据已就绪 · 补充证据读取中…"
            : lastUpdatedAt
              ? `${lastRefreshOutcome === "ERROR" ? "读取失败" : lastRefreshOutcome === "PARTIAL" ? `已读取 · ${live.partialFailures.length} 项缺失` : "证据就绪"} ${lastUpdatedAt.toLocaleTimeString("zh-CN", { hour12: false })}${lastRefreshDurationMs === undefined ? "" : ` · ${lastRefreshDurationMs} ms`}`
              : "等待连接"}
        </span>
        <button type="button" onClick={refreshReview} disabled={loading || supplementalPending || initialLoading || connection.api !== "CONNECTED"}>
          {loading || supplementalPending ? <LoaderCircle className="is-spinning" size={14} /> : <RefreshCw size={14} />} {loading || supplementalPending ? "读取中…" : "刷新证据"}
        </button>
      </div>

      <section className="review-brief" aria-labelledby="review-brief-title">
        <header className="review-brief__header">
          <div>
            <span className="review-brief__eyebrow">
              {isSyntheticDemo ? "GOAI REVIEWER · FROZEN DEMO EVIDENCE" : "GOAI REVIEWER · LOCAL API PROJECT EVIDENCE"}
            </span>
            <div className="review-brief__title-row">
              <h1 id="review-brief-title">异常案件评审台</h1>
              <StatusBadge tone="warning" compact>60 秒评审路径</StatusBadge>
            </div>
            <p>先看工业现场，再沿同一 Task 核对 Agent 补证、人工闸门与最终放行边界。</p>
          </div>
          <div className="review-brief__meta">
            <EvidenceSourceBadge source={source} />
            <span>{activeProject?.name ?? "NO PROJECT"}</span>
            {isSyntheticDemo ? <StatusBadge tone="info" compact>SAMPLE SCOPE · SYNTHETIC</StatusBadge> : null}
            {live.tasks.length ? (
              <label className="review-task-picker">
                <span>REVIEW TASK</span>
                <select
                  value={requestedTaskId}
                  onChange={(event) => selectReviewTask(event.target.value)}
                  disabled={loading || initialLoading}
                  aria-label="选择本次评审 Task"
                >
                  <option value="">LATEST · {live.tasks[0]?.task_id.slice(0, 12)}</option>
                  {live.tasks.slice(0, 20).map((task) => (
                    <option key={task.task_id} value={task.task_id}>
                      {task.task_id.slice(0, 12)} · {task.execution_status} · {task.final_decision ?? task.initial_decision ?? "NO DECISION"}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <span>只读 · 0 写请求</span>
          </div>
        </header>

        <div className="review-evidence-runway">
          <SemifinalManifestEvidence enabled={connection.api === "CONNECTED"} />
          {focusStageReady && live.task && activeWorkspace && activeProject ? (
            <section className="review-focus-stage" aria-label="案件现场、六问简报与 Agent 路由依据">
            <div
              className="review-focus-stage__visual review-visual-proof"
              id="review-visual-proof"
              tabIndex={-1}
              aria-label={isSyntheticDemo ? "冻结合成演示视觉上下文" : "当前任务冻结视觉证据"}
            >
              {isSyntheticDemo ? (
                <ReviewSyntheticAssetProof assets={live.assets} />
              ) : (
                <TaskVisualEvidencePanel
                  key={live.task.task_id}
                  taskId={live.task.task_id}
                  expectedWorkspaceId={activeWorkspace.workspace_id}
                  expectedProjectId={activeProject.project_id}
                  compact
                  onSummaryChange={setVisualEvidenceSummary}
                />
              )}
            </div>

            <aside className="review-case-briefing" aria-label="六问案件简报">
              <header>
                <div>
                  <span>CASE BRIEF · SIX QUESTIONS</span>
                  <strong>五秒读懂当前案件</strong>
                </div>
                <StatusBadge tone={statusTone(latestDecision)} compact>{latestDecision}</StatusBadge>
              </header>
              <div className="review-case-questions">
                <article className="review-case-question">
                  <span>01 · 发生了什么？</span>
                  <strong>{incident?.request.trigger.operator_message ?? live.task.goal}</strong>
                  <small>{incident ? `${incident.request.trigger.product_id} · ${incident.request.trigger.recipe_id} · ${incident.request.trigger.sample_count} samples` : live.task.task_id}</small>
                </article>
                <article className="review-case-question is-release">
                  <span>02 · 当前如何处置？</span>
                  <strong>{releaseStatusHeadline(latestDecision)}</strong>
                  <small>{incident?.recommendation ?? live.readiness?.required_human_action ?? "等待服务端发布边界"}</small>
                  <button type="button" onClick={openReleaseTruth}>查看发布边界 <ArrowRight size={11} /></button>
                </article>
                <article className="review-case-question">
                  <span>03 · 哪些事实已验证？</span>
                  <strong>{observedFact}</strong>
                  <small>{evidenceVerified ? "Evidence integrity · VERIFIED" : "证据完整性尚未通过"}</small>
                </article>
                <article className="review-case-question">
                  <span>04 · 哪些解释仍竞争？</span>
                  <strong>{alternativeSummary}</strong>
                  <small>{openHypotheses.length ? `${openHypotheses.length} 个未拒绝 hypothesis` : "不伪造根因结论"}</small>
                </article>
                <article className="review-case-question">
                  <span>05 · Agent 在做什么？</span>
                  <strong>{selectedWorkerSummary}</strong>
                  <small>{workerSelection ? `预算 ${workerSelection.selected_worker_ids.length}/${workerSelection.worker_budget}` : "等待 Incident 回执"}</small>
                </article>
                <article className="review-case-question is-next">
                  <span>06 · 人工下一步？</span>
                  <strong>{nextAction.title}</strong>
                  <small>{nextAction.detail}</small>
                </article>
              </div>

              <section className="review-agent-routing" aria-label="Agent Worker 选择与淘汰依据">
                <header>
                  <div><span>AGENT ROUTING RECEIPT</span><strong>Worker 选择与淘汰依据</strong></div>
                  <StatusBadge tone={workerSelection ? "success" : live.incidentsPending ? "neutral" : "warning"} compact>
                    {workerSelection ? "OBSERVED" : live.incidentsPending ? "READING" : "NOT OBSERVED"}
                  </StatusBadge>
                </header>
                {workerSelection ? (
                  <div className="review-agent-routing__lanes">
                    <article>
                      <span>SELECTED · {workerSelection.selected_worker_ids.length}/{workerSelection.worker_budget}</span>
                      {selectedWorkerEvidence.slice(0, 2).map(({ workerId, candidate, receipt }) => (
                        <div key={workerId}>
                          <strong>{workerId}</strong>
                          <small>{receipt?.trigger_reason_codes.length
                            ? `触发 · ${receipt.trigger_reason_codes.join(" · ")}`
                            : candidate?.discriminated_hypothesis_ids.length
                              ? `区分 ${candidate.discriminated_hypothesis_ids.join("、")}`
                              : "NO TRIGGER REASON RECORDED"}</small>
                          <em>{candidate ? `${candidate.unresolved_evidence_refs.length} gaps · ${candidate.measured_cost_bucket} cost` : "receipt-bound"}</em>
                        </div>
                      ))}
                    </article>
                    <article className="is-rejected">
                      <span>NOT SELECTED · {rejectedWorkerEvidence.length}</span>
                      {rejectedWorkerEvidence.length ? rejectedWorkerEvidence.map((entry) => (
                        <div key={entry.worker_id}>
                          <strong>{entry.worker_id}</strong>
                          <small>{entry.exclusion_reasons[0] ?? entry.candidate?.ineligibility_reasons[0] ?? "预算或排序未命中"}</small>
                          <em>{entry.eligible ? "eligible · not selected" : "ineligible"}</em>
                        </div>
                      )) : <p>没有可展示的淘汰 Worker。</p>}
                    </article>
                  </div>
                ) : <p>{live.incidentsPending ? "正在读取 Incident v5/v6 补证回执。" : "当前 Task 没有可引用的 Worker Selection Receipt；页面不会补写路由理由。"}</p>}
              </section>
            </aside>

            <div className="review-source-contract" aria-label="当前证据来源合同">
              <span><strong>READ PATH</strong><em>{source === "LIVE_API" ? "LOCAL API LIVE · READ ONLY" : "NOT CONNECTED"}</em></span>
              <span><strong>IMAGE INPUT</strong><em>{isSyntheticDemo ? "FROZEN DEMO INPUT" : "TASK FROZEN INPUT"}</em></span>
              <span><strong>OPC UA</strong><em>{opcuaSourceMode}</em></span>
              <span><strong>PLANNER</strong><em>{String(plannerMode).toUpperCase()}</em></span>
              <span><strong>DEVICE CONTROL</strong><em>NOT PERMITTED</em></span>
            </div>
            </section>
          ) : null}
        </div>

        <div className="review-truthline" aria-label="当前项目核心评审结论">
          <article>
            <span>01 · {isSyntheticDemo ? "SAMPLE SCOPE" : "INPUT SCOPE"}</span>
            <strong>{initialLoading
              ? "读取中…"
              : assetsUnavailable
                ? "UNAVAILABLE"
                : isSyntheticDemo
                  ? `${live.assets.length} 张冻结演示资产`
                : currentVisualSummary
                  ? `工作簿 ${live.assets.length} · 任务冻结 ${currentVisualSummary.visual_count}`
                  : `${live.assets.length} 张工作簿图像`}</strong>
            <small>{initialLoading
              ? "正在绑定当前项目范围"
              : isSyntheticDemo
                ? "仅证明隔离产品闭环；不计入工厂效果或 Task 冻结视觉分母"
              : currentVisualSummary
                ? `本次任务命中 ${currentVisualSummary.affected_count} 张；冻结分母与当前工作簿分开`
                : live.assets.length
                  ? "当前工作簿资产；任务分母以冻结快照为准"
                  : "尚无可验证输入"}</small>
          </article>
          <ArrowRight size={18} aria-hidden="true" />
          <article>
            <span>02 · AGENT</span>
            <strong>{initialLoading ? "读取中…" : taskStatusHeadline(live.task?.execution_status)}</strong>
            <small>{initialLoading ? "正在读取任务与事件" : live.task ? eventsUnavailable ? `${live.task.execution_status} · 运行事件不可用` : `${live.task.execution_status} · ${live.events.length} events · ${completedToolEvents} tool success` : "等待受控任务合同"}</small>
          </article>
          <ArrowRight size={18} aria-hidden="true" />
          <article className="is-release">
            <span>03 · RELEASE TRUTH</span>
            <strong>{initialLoading ? "核验中…" : releaseStatusHeadline(latestDecision)}</strong>
            <small>{initialLoading ? "等待服务端发布边界" : `${latestDecision} · production release=false`}</small>
          </article>
        </div>

        <ol className="review-checkpoints" aria-label="评审证据检查点">
          {checkpoints.map((checkpoint, index) => {
            const state = checkpointState(checkpoint, index);
            const stateLabel = checkpointStateLabel(checkpoint, state);
            const Icon = checkpoint.icon;
            return (
              <li key={checkpoint.id} data-state={state}>
                <button
                  type="button"
                  onClick={() => openCheckpoint(checkpoint)}
                  aria-label={`${checkpoint.label}：${checkpoint.detail}；状态：${stateLabel}`}
                  aria-current={state === "active" ? "step" : undefined}
                  aria-controls={checkpoint.id === "input" && live.task?.execution_status === "COMPLETED" && (isSyntheticDemo || evidenceVerified) ? "review-visual-proof" : undefined}
                >
                  <span className="review-checkpoints__index">{String(index + 1).padStart(2, "0")}</span>
                  <Icon size={17} aria-hidden="true" />
                  <strong>{checkpoint.label}</strong>
                  <small>{checkpoint.detail}</small>
                  <em>{stateLabel}</em>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="review-next-action">
          <NextActionIcon size={20} aria-hidden="true" />
          <div>
            <span>{nextAction.eyebrow}</span>
            <strong>{nextAction.title}</strong>
            <small>{nextAction.detail}</small>
          </div>
          <ActionButton icon={nextAction.icon} onClick={nextAction.run} disabled={nextActionDisabled}>
            {nextAction.label}
          </ActionButton>
        </div>
      </section>

      {connection.api !== "CONNECTED" ? (
        <div className="review-empty-state">
          <EmptyState icon={LockKeyhole} title="本地 API 未连接" description="评审页不会回退到冻结 Dashboard。连接 API 后读取当前项目的只读证据。" />
          <ActionButton icon={RefreshCw} onClick={() => void refreshConnection()} disabled={connectionRefreshing}>
            {connectionRefreshing ? "正在检测 API…" : "重新检测 API"}
          </ActionButton>
        </div>
      ) : !activeProject || !activeWorkspace ? (
        <div className="review-empty-state">
          <EmptyState icon={Inbox} title="尚未选择真实项目" description="先在左侧创建或选择项目，再形成项目级评审视图。" />
          <ActionButton icon={Images} onClick={() => navigate("/workspace")}>前往图像工作簿</ActionButton>
        </div>
      ) : error ? (
        <div className="review-live-notice is-error" role="alert">
          <TriangleAlert size={15} />
          <span><strong>无法读取评审证据</strong>{error}</span>
          <button type="button" onClick={refreshReview}>重试</button>
        </div>
      ) : initialLoading ? (
        <div className="review-loading-state" role="status">
          <LoaderCircle className="is-spinning" size={17} />
          <span><strong>正在汇总项目回执</strong>保留缺失项，不跨项目或跨来源补位。</span>
        </div>
      ) : !live.task ? (
        <>
          {live.partialFailures.length ? (
            <div className="review-live-notice is-warning" role="status">
              <TriangleAlert size={15} />
              <span><strong>部分证据读取失败</strong>{live.partialFailures.join("、")}；缺失项不会被解释成“没有数据”。</span>
              <button type="button" onClick={refreshReview} disabled={loading}>重新读取</button>
            </div>
          ) : null}
          <div className="review-evidence-barrier" role="status">
            <NextActionIcon size={18} aria-hidden="true" />
            <div>
              <span>WHY EVIDENCE STOPS HERE</span>
              <strong>{taskSelectionUnavailable
                ? "指定 Task 不属于当前项目"
                : taskIndexUnavailable
                  ? "Task 索引不可用，当前状态无法判断"
                  : assetsUnavailable
                    ? "图像资产索引不可用，当前输入无法判断"
                    : live.assets.length
                      ? "输入已就绪，尚无 Agent Task"
                      : "当前项目尚无可验证输入"}</strong>
              <p>{taskSelectionUnavailable
                ? "切回当前项目的最新 Task，或从任务页打开一个明确的深链。"
                : taskIndexUnavailable || assetsUnavailable
                  ? "重新读取失败的只读索引；恢复前不推断任务或输入是否存在。"
                  : live.assets.length
                    ? `已读取 ${live.assets.length} 张项目图像；创建并运行受控 Task 后才会生成运行、证据和血缘回执。`
                    : isSyntheticDemo
                      ? "冻结演示资产缺失；请重新执行隔离 Demo 准备，不会从其他项目补位。"
                      : "先导入真实图片或数据集。系统不会用样例回执填充后续评审结果。"}</p>
            </div>
            <StatusBadge tone="warning" compact>{taskSelectionUnavailable
              ? "TASK SCOPE MISMATCH"
              : taskIndexUnavailable
                ? "TASK INDEX UNAVAILABLE"
                : assetsUnavailable
                  ? "ASSET INDEX UNAVAILABLE"
                  : live.assets.length
                    ? "TASK REQUIRED"
                    : "INPUT REQUIRED"}</StatusBadge>
          </div>
        </>
      ) : (
        <>
          {live.partialFailures.length ? (
            <div className="review-live-notice is-warning" role="status">
              <TriangleAlert size={15} />
              <span><strong>部分证据读取失败</strong>{live.partialFailures.join("、")}；其余证据仍按真实响应显示。</span>
              <button type="button" onClick={refreshReview} disabled={loading}>重新读取</button>
            </div>
          ) : null}

          <ReviewInteractionBridge
            taskId={live.task.task_id}
            incidents={live.incidents}
            incidentsPending={live.incidentsPending}
            incidentsUnavailable={incidentsUnavailable}
          />

          {incident ? (
            <IncidentReviewProjectionPanel
              taskId={live.task.task_id}
              caseId={incident.case_id}
              surface="reviewer"
            />
          ) : null}

          <div className="review-score-strip">
            <Metric label="任务闭环" value={live.task.execution_status} detail={live.task.final_decision ?? "无最终裁决"} tone={statusTone(live.task.execution_status)} />
            <Metric label="运行活动" value={eventsUnavailable ? "UNAVAILABLE" : `${live.events.length} events`} detail={eventsUnavailable ? "事件索引读取失败" : `${completedToolEvents} 个成功 Tool 事件`} tone={eventsUnavailable ? "warning" : "info"} />
            <Metric
              label="动态补证"
              value={live.incidentsPending ? "读取中…" : incidentsUnavailable ? "UNAVAILABLE" : incident ? `${incident.worker_selection_receipt.selected_worker_ids.length} Workers` : "NOT MEASURED"}
              detail={live.incidentsPending ? "核心任务已就绪，正在读取补充 Incident" : incidentsUnavailable ? "Incident 回执读取失败" : incident ? incident.recommendation : "尚无 Incident v5/v6"}
              tone={live.incidentsPending ? "info" : incident ? "warning" : "neutral"}
            />
            <Metric
              label="历史影子"
              value={
                live.governanceSummaryPending
                  ? "读取中…"
                  : live.governanceSummaryFailed
                  ? "UNAVAILABLE"
                  : `${live.governanceSummary?.receipt_count ?? 0} receipts`
              }
              detail={
                live.governanceSummaryPending
                  ? "核心任务已就绪，治理汇总渐进加载"
                  : groupedConfusion
                  ? `${live.governanceSummary?.confusion_groups.length ?? 0} 个分析单位 · 禁止合并`
                  : `${rateCounts(singleConfusionGroup?.false_release_rate)} 误放行`
              }
              tone={live.governanceSummaryPending ? "info" : live.governanceSummary?.receipt_count ? "success" : "neutral"}
            />
          </div>

          <div className="review-hero-grid">
            <Panel variant="raised">
              <PanelHeader
                eyebrow="01 · LATEST TASK"
                title={live.task.goal}
                detail={`${live.task.task_id} · ${live.task.source_kind}`}
                actions={<StatusBadge tone={statusTone(live.task.execution_status)} compact>{live.task.execution_status}</StatusBadge>}
              />
              <div className="review-boundaries">
                <DetailRow label="business decision" value={live.task.final_decision ?? live.task.initial_decision ?? "UNAVAILABLE"} />
                <DetailRow label="runtime status" value={live.task.runtime_status ?? "UNAVAILABLE"} />
                <DetailRow label="request SHA" value={compactDigest(live.task.request_sha256)} />
                <DetailRow label="evidence SHA" value={compactDigest(live.task.evidence_sha256)} />
              </div>
              <div className="review-live-actions">
                <ActionButton variant="secondary" icon={Activity} onClick={() => navigate(taskHref("/runs"))}>打开运行账本</ActionButton>
                <ActionButton variant="secondary" icon={FileCheck2} onClick={() => navigate(evidenceHref)}>打开证据清单</ActionButton>
              </div>
            </Panel>

            <Panel variant="raised">
              <PanelHeader
                eyebrow="02 · AGENT LOOP"
                title="可审计阶段活动"
                detail="显示结构化事件，不展示或伪造模型私有思维链。"
                actions={<StatusBadge tone={eventsUnavailable ? "danger" : live.events.length ? "success" : "warning"} compact>{eventsUnavailable ? "READ FAILED" : live.events.length ? "OBSERVED" : "NOT OBSERVED"}</StatusBadge>}
              />
              <div className="review-live-ledger">
                {eventPreview.length ? eventPreview.map((event) => (
                  <article key={`${event.task_id}-${event.sequence}`}>
                    <span>{String(event.sequence).padStart(2, "0")}</span>
                    <div><strong>{event.stage} · {event.phase}</strong><small>{event.summary}</small></div>
                    <StatusBadge tone={statusTone(event.status)} compact>{event.status}</StatusBadge>
                  </article>
                )) : <p>{eventsUnavailable ? "UNAVAILABLE · 运行事件读取失败。" : "NOT OBSERVED · 服务端尚未记录运行事件。"}</p>}
              </div>
            </Panel>
          </div>

          <Panel variant="raised">
            <PanelHeader
              eyebrow="03 · PROVENANCE"
              title="Parent / Child 与 CAPA 血缘"
              detail={live.readiness?.evidence_integrity === "FAILED"
                ? "证据完整性失败，前端不请求或展示可能误导的 lineage report。"
                : "节点和边只来自当前 Task 的服务端 lineage report。"}
              actions={<StatusBadge tone={live.lineage ? "success" : "warning"} compact>{live.lineage ? "VERIFIED REPORT" : "UNAVAILABLE"}</StatusBadge>}
            />
            <div className="review-lineage-summary">
              <article><span>nodes</span><strong>{live.lineage?.node_count ?? "—"}</strong><small>任务节点</small></article>
              <article><span>edges</span><strong>{live.lineage?.edge_count ?? "—"}</strong><small>复验边</small></article>
              <article><span>CAPA</span><strong>{live.capasPending ? "…" : capasUnavailable ? "—" : live.capas.length}</strong><small>{live.capasPending ? "正在读取" : capasUnavailable ? "读取失败" : "受控案件"}</small></article>
              <article><span>latest</span><strong>{compactDigest(live.lineage?.latest_task_id)}</strong><small>最新 Task</small></article>
            </div>
            {live.lineage ? <Digest label="LINEAGE REPORT SHA-256" value={live.lineage.report_sha256} /> : null}
            <div className="review-live-actions"><ActionButton variant="secondary" icon={GitBranch} onClick={() => navigate(taskHref("/lineage"))}>查看完整血缘</ActionButton></div>
          </Panel>

          <div className="review-evidence-grid">
            <Panel id="review-release-truth">
              <PanelHeader
                eyebrow="04 · GOVERNANCE EFFECTIVENESS"
                title="授权历史批次治理指标"
                detail="只读取后端项目级哈希汇总；不在浏览器跨回执或跨分析单位相加。"
                actions={<StatusBadge tone={live.governanceSummaryPending ? "neutral" : live.governanceSummary?.measurement_status === "MEASURED" ? "success" : "warning"} compact>{live.governanceSummaryPending ? "READING" : live.governanceSummaryFailed ? "UNAVAILABLE" : live.governanceSummary?.measurement_status ?? "NOT MEASURED"}</StatusBadge>}
              />
              {live.governanceSummaryPending ? (
                <div className="review-progressive-loading" role="status">
                  <LoaderCircle className="is-spinning" size={17} />
                  <span><strong>正在读取历史治理汇总</strong>主任务与发布边界已经可用；此区域完成后独立更新。</span>
                </div>
              ) : (
                <div className="review-benchmarks">
                  <article><div><strong>误放行率</strong><StatusBadge tone="danger" compact>{groupedConfusion ? `${live.governanceSummary?.confusion_groups.length ?? 0} UNITS` : rateCounts(singleConfusionGroup?.false_release_rate)}</StatusBadge></div><p>{groupedConfusion ? "GROUPED" : formatRate(singleConfusionGroup?.false_release_rate)}</p><small>{groupedConfusion ? "分析单位不兼容，不生成跨组总率" : `误放行 / 应拦截 · ${singleConfusionGroup?.unit_of_analysis ?? "NOT MEASURED"}`}</small></article>
                  <article><div><strong>误拦截率</strong><StatusBadge tone="warning" compact>{groupedConfusion ? `${live.governanceSummary?.confusion_groups.length ?? 0} UNITS` : rateCounts(singleConfusionGroup?.false_block_rate)}</StatusBadge></div><p>{groupedConfusion ? "GROUPED" : formatRate(singleConfusionGroup?.false_block_rate)}</p><small>{groupedConfusion ? "每组结果在治理页独立展示" : `误拦截 / 可放行 · ${singleConfusionGroup?.unit_of_analysis ?? "NOT MEASURED"}`}</small></article>
                  <article><div><strong>整改后通过率</strong><StatusBadge tone="success" compact>{rateCounts(live.governanceSummary?.verified_remediation_pass_rate)}</StatusBadge></div><p>{formatRate(live.governanceSummary?.verified_remediation_pass_rate)}</p><small>后端同合同复验汇总</small></article>
                  <article><div><strong>整改未决率</strong><StatusBadge tone="warning" compact>{rateCounts(live.governanceSummary?.unresolved_remediation_rate)}</StatusBadge></div><p>{formatRate(live.governanceSummary?.unresolved_remediation_rate)}</p><small>后端全部整改尝试汇总</small></article>
                </div>
              )}
              {groupedConfusion ? (
                <ClaimBoundary title="分析单位边界" tone="warning">
                  后端返回 GROUPED_BY_UNIT：{live.governanceSummary?.confusion_groups.map((group) => group.unit_of_analysis).join("、")}。评审页不生成跨单位总准确率。
                </ClaimBoundary>
              ) : null}
              {live.governanceSummary ? <Digest label="PROJECT GOVERNANCE SUMMARY SHA-256" value={live.governanceSummary.summary_sha256} /> : null}
              <div className="review-live-actions"><ActionButton variant="secondary" icon={ShieldCheck} onClick={() => navigate(taskHref("/governance"))}>查看回执明细</ActionButton></div>
            </Panel>

            <Panel>
              <PanelHeader
                eyebrow="05 · RELEASE TRUTH"
                title="当前任务发布就绪边界"
                detail="任务完成、人工审阅与生产放行是三个独立状态。"
                actions={<StatusBadge tone={statusTone(live.readiness?.overall_status ?? "UNAVAILABLE")} compact>{live.readiness?.overall_status ?? "UNAVAILABLE"}</StatusBadge>}
              />
              <div className="review-boundaries">
                <DetailRow label="evidence integrity" value={live.readiness?.evidence_integrity ?? "UNAVAILABLE"} />
                <DetailRow label="source freshness" value={live.readiness?.source_freshness ?? "UNAVAILABLE"} />
                <DetailRow label="open work orders" value={live.readiness?.open_work_order_count ?? "UNAVAILABLE"} />
                <DetailRow label="production release" value={<StatusBadge tone="danger">false</StatusBadge>} />
                <DetailRow label="required human action" value={live.readiness?.required_human_action ?? "等待可验证回执"} />
              </div>
              {live.readiness ? <Digest label="READINESS REPORT SHA-256" value={live.readiness.report_sha256} /> : null}
            </Panel>
          </div>
        </>
      )}

      <EvaluationEvidencePanel
        id="dynamicbench-evidence"
        surface="review"
        scope={connection.api === "CONNECTED" ? { kind: "GLOBAL_REVIEW" } : undefined}
      />

      <div className="review-authority-boundary" aria-label="评委只读权限证明">
        <strong><LockKeyhole size={16} /> 评委只读权限</strong>
        <span><FileCheck2 size={15} /> CAPA 决定 · 仅查看</span>
        <span><ShieldCheck size={15} /> Child Run · 仅查看</span>
        <span><LockKeyhole size={15} /> 生产放行 · 人工专属</span>
        <em><BookOpenCheck size={15} /> 本页不会发送业务写请求</em>
      </div>

      <ClaimBoundary title="评委页面声明" tone="info">
        当前页面只汇总本机 API 返回的项目级只读证据；接口失败时保持缺失，不用 fixture 补位。历史影子回执仍是操作者声明绑定的评测证据，
        不等于客户验收；本地任务、SHA 完整性与 UI 可运行也不等于生产部署、官方提交或官方评测通过。
      </ClaimBoundary>
    </div>
  );
}
