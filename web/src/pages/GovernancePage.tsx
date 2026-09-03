import {
  BarChart3,
  ArrowRight,
  Braces,
  DatabaseZap,
  Download,
  FileCheck2,
  FileJson,
  Fingerprint,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import type { AgentReleaseReadiness, AgentTask } from "../agentDomain";
import {
  ActionButton,
  ClaimBoundary,
  DetailRow,
  Digest,
  EvidenceSourceBadge,
  Metric,
  Panel,
  PanelHeader,
  StatusBadge,
  SystemHubHero,
} from "../components/ui";
import {
  createShadowEvaluationManifestV2,
  getAgentReleaseReadiness,
  getProjectGovernanceEffectiveness,
  listAgentTasks,
  listIndustrialShadowEvaluations,
  listShadowEvaluationManifestsV2,
} from "../data/api";
import type {
  CreateShadowEvaluationManifestV2Input,
  GovernanceRateMetric,
  IndustrialShadowEvaluationReceipt,
  ProjectGovernanceEffectivenessSummary,
  ShadowEvaluationManifestV2,
  ShadowEvaluationUnitV2,
} from "../governanceDomain";
import type { StatusTone } from "../domain";
import { useProduct } from "../ProductContext";
import { EvaluationEvidencePanel } from "../components/EvaluationEvidencePanel";
import { PrivateIndustrialValidationPanel } from "../components/PrivateIndustrialValidationPanel";

interface ShadowManifestImportState {
  taskId: string;
  fileName: string;
  draft?: Omit<
    CreateShadowEvaluationManifestV2Input,
    | "operator_attests_authorized_historical_use"
    | "operator_attests_labels_reviewed"
  >;
  authorizedAttested: boolean;
  labelsReviewedAttested: boolean;
}

const emptyManifestImport: ShadowManifestImportState = {
  taskId: "",
  fileName: "",
  authorizedAttested: false,
  labelsReviewedAttested: false,
};

const sha256Pattern = /^[0-9a-f]{64}$/;
const unitIdPattern = /^unit_[0-9a-f]{16,64}$/;

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} 必须是 JSON object`);
  }
  return value as Record<string, unknown>;
}

function stringField(value: unknown, label: string, minimum = 1): string {
  if (typeof value !== "string" || value.trim().length < minimum) {
    throw new Error(`${label} 必须是至少 ${minimum} 个字符的字符串`);
  }
  return value.trim();
}

function rejectUnexpectedKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
  label: string,
): void {
  const unexpected = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unexpected.length) {
    throw new Error(
      `${label} 包含不允许字段：${unexpected.join("、")}；聚合计数与 Manifest SHA 必须由服务端生成`,
    );
  }
}

function parseManifestUnit(value: unknown, index: number): ShadowEvaluationUnitV2 {
  const unit = record(value, `units[${index}]`);
  rejectUnexpectedKeys(
    unit,
    [
      "unit_id",
      "truth_disposition",
      "gate_disposition",
      "truth_evidence_sha256",
      "gate_evidence_sha256",
      "remediation_outcome",
      "remediation_evidence_sha256",
    ],
    `units[${index}]`,
  );
  const unitId = stringField(unit.unit_id, `units[${index}].unit_id`);
  if (!unitIdPattern.test(unitId)) {
    throw new Error(`units[${index}].unit_id 必须匹配 unit_ + 16–64 位小写十六进制`);
  }
  if (unit.truth_disposition !== "BLOCK" && unit.truth_disposition !== "RELEASE") {
    throw new Error(`units[${index}].truth_disposition 只能是 BLOCK 或 RELEASE`);
  }
  if (unit.gate_disposition !== "BLOCK" && unit.gate_disposition !== "RELEASE") {
    throw new Error(`units[${index}].gate_disposition 只能是 BLOCK 或 RELEASE`);
  }
  const truthEvidenceSha256 = stringField(
    unit.truth_evidence_sha256,
    `units[${index}].truth_evidence_sha256`,
  );
  const gateEvidenceSha256 = stringField(
    unit.gate_evidence_sha256,
    `units[${index}].gate_evidence_sha256`,
  );
  if (!sha256Pattern.test(truthEvidenceSha256) || !sha256Pattern.test(gateEvidenceSha256)) {
    throw new Error(`units[${index}] 的 Truth/Gate 证据 SHA 必须是 64 位小写十六进制`);
  }
  const remediationOutcome = unit.remediation_outcome ?? "NOT_APPLICABLE";
  if (
    remediationOutcome !== "NOT_APPLICABLE" &&
    remediationOutcome !== "UNRESOLVED" &&
    remediationOutcome !== "VERIFIED_PASS" &&
    remediationOutcome !== "VERIFIED_FAIL"
  ) {
    throw new Error(`units[${index}].remediation_outcome 不在允许枚举中`);
  }
  const remediationEvidenceSha256 =
    unit.remediation_evidence_sha256 === undefined ||
    unit.remediation_evidence_sha256 === null
      ? null
      : stringField(
          unit.remediation_evidence_sha256,
          `units[${index}].remediation_evidence_sha256`,
        );
  if (remediationOutcome === "NOT_APPLICABLE" && remediationEvidenceSha256 !== null) {
    throw new Error(`units[${index}] 未整改时不能附带整改证据 SHA`);
  }
  if (
    remediationOutcome !== "NOT_APPLICABLE" &&
    (remediationEvidenceSha256 === null || !sha256Pattern.test(remediationEvidenceSha256))
  ) {
    throw new Error(`units[${index}] 有整改结果时必须提供 64 位整改证据 SHA`);
  }
  return {
    unit_id: unitId,
    truth_disposition: unit.truth_disposition,
    gate_disposition: unit.gate_disposition,
    truth_evidence_sha256: truthEvidenceSha256,
    gate_evidence_sha256: gateEvidenceSha256,
    remediation_outcome: remediationOutcome,
    remediation_evidence_sha256: remediationEvidenceSha256,
  };
}

function parseShadowManifestDraft(
  value: unknown,
): ShadowManifestImportState["draft"] {
  const manifest = record(value, "manifest");
  rejectUnexpectedKeys(
    manifest,
    [
      "schema_version",
      "identity",
      "unit_of_analysis",
      "ground_truth_method",
      "units",
      "note",
    ],
    "manifest",
  );
  if (
    manifest.schema_version !== undefined &&
    manifest.schema_version !== "visiondata-gate.shadow-evaluation-import.v2"
  ) {
    throw new Error("schema_version 必须是 visiondata-gate.shadow-evaluation-import.v2");
  }
  const identity = record(manifest.identity, "identity");
  rejectUnexpectedKeys(
    identity,
    [
      "dataset_namespace",
      "site_alias",
      "line_alias",
      "station_alias",
      "camera_alias",
      "batch_alias",
      "captured_from",
      "captured_to",
    ],
    "identity",
  );
  const capturedFrom = stringField(identity.captured_from, "identity.captured_from");
  const capturedTo = stringField(identity.captured_to, "identity.captured_to");
  if (Number.isNaN(Date.parse(capturedFrom)) || Number.isNaN(Date.parse(capturedTo))) {
    throw new Error("identity.captured_from / captured_to 必须是带时区的 ISO 时间");
  }
  if (Date.parse(capturedFrom) > Date.parse(capturedTo)) {
    throw new Error("identity.captured_from 不能晚于 captured_to");
  }
  if (
    manifest.ground_truth_method !== "quality_owner_adjudication" &&
    manifest.ground_truth_method !== "dual_human_adjudication" &&
    manifest.ground_truth_method !== "existing_qms_disposition"
  ) {
    throw new Error("ground_truth_method 不在允许枚举中");
  }
  if (!Array.isArray(manifest.units) || manifest.units.length < 1) {
    throw new Error("units 至少需要 1 条逐单元记录");
  }
  if (manifest.units.length > 10_000) {
    throw new Error("units 不能超过 10,000 条");
  }
  const units = manifest.units.map(parseManifestUnit);
  if (new Set(units.map((unit) => unit.unit_id)).size !== units.length) {
    throw new Error("units 中存在重复 unit_id");
  }
  return {
    identity: {
      dataset_namespace: stringField(identity.dataset_namespace, "identity.dataset_namespace", 2),
      site_alias: stringField(identity.site_alias, "identity.site_alias", 2),
      line_alias: stringField(identity.line_alias, "identity.line_alias", 2),
      station_alias: stringField(identity.station_alias, "identity.station_alias", 2),
      camera_alias: stringField(identity.camera_alias, "identity.camera_alias", 2),
      batch_alias: stringField(identity.batch_alias, "identity.batch_alias", 2),
      captured_from: capturedFrom,
      captured_to: capturedTo,
    },
    unit_of_analysis: stringField(manifest.unit_of_analysis, "unit_of_analysis", 2),
    ground_truth_method: manifest.ground_truth_method,
    units,
    note: stringField(manifest.note, "note", 8),
  };
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : "本地 API 请求失败";
}

function formatRate(metric: GovernanceRateMetric | undefined): string {
  if (!metric || metric.status !== "MEASURED" || metric.value === null) {
    return metric?.status.replaceAll("_", " ") ?? "NOT MEASURED";
  }
  return `${(metric.value * 100).toFixed(2)}%`;
}

function metricTone(
  metric: GovernanceRateMetric | undefined,
  measuredTone: StatusTone = "danger",
): StatusTone {
  if (!metric || metric.status !== "MEASURED") return "warning";
  return metric.numerator === 0 ? "success" : measuredTone;
}

function readinessTone(status: AgentReleaseReadiness["overall_status"]): StatusTone {
  if (status === "READY_FOR_HUMAN_REVIEW") return "success";
  if (status === "DEMO_ONLY") return "warning";
  return "danger";
}

function readinessCheckTone(
  status: AgentReleaseReadiness["checks"][number]["status"],
): StatusTone {
  if (status === "PASS") return "success";
  if (status === "BLOCKED") return "danger";
  if (status === "PENDING") return "warning";
  return "neutral";
}

export function GovernancePage() {
  const navigate = useNavigate();
  const { activeWorkspace, activeProject, connection } = useProduct();
  const [eligibleTasks, setEligibleTasks] = useState<AgentTask[]>([]);
  const [receipts, setReceipts] = useState<IndustrialShadowEvaluationReceipt[]>([]);
  const [manifestReceipts, setManifestReceipts] = useState<ShadowEvaluationManifestV2[]>([]);
  const [governanceSummary, setGovernanceSummary] =
    useState<ProjectGovernanceEffectivenessSummary>();
  const [governanceSummaryError, setGovernanceSummaryError] = useState<string>();
  const [releaseTask, setReleaseTask] = useState<AgentTask>();
  const [releaseReadiness, setReleaseReadiness] = useState<AgentReleaseReadiness>();
  const [releaseError, setReleaseError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const [feedback, setFeedback] = useState<string>();
  const [refreshToken, setRefreshToken] = useState(0);
  const [manifestImport, setManifestImport] =
    useState<ShadowManifestImportState>(emptyManifestImport);

  useEffect(() => {
    let active = true;
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    setEligibleTasks([]);
    setReceipts([]);
    setManifestReceipts([]);
    setManifestImport(emptyManifestImport);
    setGovernanceSummary(undefined);
    setGovernanceSummaryError(undefined);
    setReleaseTask(undefined);
    setReleaseReadiness(undefined);
    setReleaseError(undefined);
    setError(undefined);
    setFeedback(undefined);
    if (!workspaceId || !projectId) {
      setGovernanceSummaryError("未选择工作区或项目，项目级治理汇总不可读取。");
      return () => {
        active = false;
      };
    }
    if (connection.api !== "CONNECTED") {
      setGovernanceSummaryError("本地 API 未连接，项目级治理汇总不可读取。");
      return () => {
        active = false;
      };
    }
    setLoading(true);
    void (async () => {
      try {
        const [tasksResult, summaryResult] = await Promise.allSettled([
          listAgentTasks(workspaceId, projectId),
          getProjectGovernanceEffectiveness(projectId),
        ]);
        if (!active) return;
        if (summaryResult.status === "fulfilled") {
          setGovernanceSummary(summaryResult.value);
        } else {
          setGovernanceSummaryError(
            `项目级治理汇总不可读取：${readableError(summaryResult.reason)}`,
          );
        }
        if (tasksResult.status === "rejected") {
          setError(`任务与影子回执明细不可读取：${readableError(tasksResult.reason)}`);
          return;
        }
        const tasks = tasksResult.value;
        const eligible = tasks.filter(
          (task) =>
            task.workspace_id === workspaceId &&
            task.project_id === projectId &&
            task.execution_status === "COMPLETED" &&
            task.source_kind === "local_authorized_directory" &&
            Boolean(task.source_id) &&
            Boolean(task.evidence_sha256),
        );
        const latestCompletedTask = tasks
          .filter(
            (task) =>
              task.execution_status === "COMPLETED" && Boolean(task.evidence_sha256),
          )
          .sort((left, right) =>
            (right.completed_at ?? right.updated_at).localeCompare(
              left.completed_at ?? left.updated_at,
            ),
          )[0];
        const [results, manifestResults, readinessResult] = await Promise.all([
          Promise.allSettled(
            eligible.map((task) => listIndustrialShadowEvaluations(task.task_id)),
          ),
          Promise.allSettled(
            eligible.map((task) => listShadowEvaluationManifestsV2(task.task_id)),
          ),
          latestCompletedTask
            ? Promise.allSettled([getAgentReleaseReadiness(latestCompletedTask.task_id)]).then(
                ([result]) => result,
              )
            : Promise.resolve(undefined),
        ]);
        if (!active) return;
        const nextReceipts: IndustrialShadowEvaluationReceipt[] = [];
        const nextManifestReceipts: ShadowEvaluationManifestV2[] = [];
        const failures: string[] = [];
        results.forEach((result, index) => {
          if (result.status === "fulfilled") nextReceipts.push(...result.value);
          else failures.push(`${eligible[index]?.task_id ?? "unknown"} legacy: ${readableError(result.reason)}`);
        });
        manifestResults.forEach((result, index) => {
          if (result.status === "fulfilled") nextManifestReceipts.push(...result.value);
          else failures.push(`${eligible[index]?.task_id ?? "unknown"} v2: ${readableError(result.reason)}`);
        });
        nextReceipts.sort((left, right) => right.created_at.localeCompare(left.created_at));
        nextManifestReceipts.sort((left, right) =>
          right.created_at.localeCompare(left.created_at),
        );
        setEligibleTasks(eligible);
        setReceipts(nextReceipts);
        setManifestReceipts(nextManifestReceipts);
        setReleaseTask(latestCompletedTask);
        if (readinessResult?.status === "fulfilled") {
          setReleaseReadiness(readinessResult.value);
        } else if (readinessResult?.status === "rejected") {
          setReleaseError(`当前任务发布就绪不可读取：${readableError(readinessResult.reason)}`);
        }
        setManifestImport((current) => ({
          ...current,
          taskId: eligible.some((task) => task.task_id === current.taskId)
            ? current.taskId
            : (eligible[0]?.task_id ?? ""),
        }));
        if (failures.length) setError(`部分影子回执不可读取：${failures.join("；")}`);
      } catch (caught) {
        if (active) setError(readableError(caught));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [
    activeProject?.project_id,
    activeWorkspace?.workspace_id,
    connection.api,
    refreshToken,
  ]);

  const singleConfusionGroup = useMemo(
    () =>
      governanceSummary?.confusion_pooling_status === "SINGLE_UNIT"
        ? governanceSummary.confusion_groups[0]
        : undefined,
    [governanceSummary],
  );
  const confusionIsGrouped =
    governanceSummary?.confusion_pooling_status === "GROUPED_BY_UNIT";
  const currentReleaseOutcome = releaseReadiness?.final_gate_decision ?? "NOT MEASURED";
  const currentReleaseStatus = releaseReadiness?.overall_status ?? "UNAVAILABLE";

  const updateManifestImport = <K extends keyof ShadowManifestImportState>(
    key: K,
    value: ShadowManifestImportState[K],
  ) => {
    setManifestImport((current) => ({ ...current, [key]: value }));
  };

  const importManifestFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(undefined);
    setFeedback(undefined);
    try {
      if (!file.name.toLowerCase().endsWith(".json")) {
        throw new Error("只接受 .json 逐单元 Manifest");
      }
      if (file.size > 20 * 1024 * 1024) {
        throw new Error("Manifest 文件不能超过 20 MiB");
      }
      const parsed = parseShadowManifestDraft(JSON.parse(await file.text()));
      if (!parsed) throw new Error("Manifest 内容为空");
      setManifestImport((current) => ({
        ...current,
        fileName: file.name,
        draft: parsed,
        authorizedAttested: false,
        labelsReviewedAttested: false,
      }));
      setFeedback(
        `已在浏览器本地校验 ${file.name}：${parsed.units.length} 条逐单元记录；尚未提交。`,
      );
    } catch (caught) {
      setManifestImport((current) => ({
        ...current,
        fileName: file.name,
        draft: undefined,
        authorizedAttested: false,
        labelsReviewedAttested: false,
      }));
      setError(`Manifest 导入失败：${readableError(caught)}`);
    }
  };

  const downloadManifestTemplate = () => {
    const template = {
      schema_version: "visiondata-gate.shadow-evaluation-import.v2",
      identity: {
        dataset_namespace: "authorized-history-v1",
        site_alias: "site-a",
        line_alias: "line-01",
        station_alias: "aoi-07",
        camera_alias: "camera-main",
        batch_alias: "batch-2026-08-29-a",
        captured_from: "2026-08-20T00:00:00+08:00",
        captured_to: "2026-08-21T00:00:00+08:00",
      },
      unit_of_analysis: "inspection image",
      ground_truth_method: "dual_human_adjudication",
      units: [
        {
          unit_id: "unit_0000000000000001",
          truth_disposition: "BLOCK",
          gate_disposition: "BLOCK",
          truth_evidence_sha256: "REPLACE_WITH_64_LOWERCASE_HEX",
          gate_evidence_sha256: "REPLACE_WITH_64_LOWERCASE_HEX",
          remediation_outcome: "NOT_APPLICABLE",
          remediation_evidence_sha256: null,
        },
      ],
      note: "Describe who reviewed the per-unit truth and Gate evidence.",
    };
    const url = URL.createObjectURL(
      new Blob([`${JSON.stringify(template, null, 2)}\n`], {
        type: "application/json",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "shadow-evaluation-import-v2.template.json";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const submitManifest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting || !manifestImport.taskId || !manifestImport.draft) return;
    setSubmitting(true);
    setError(undefined);
    setFeedback(undefined);
    try {
      if (!manifestImport.authorizedAttested || !manifestImport.labelsReviewedAttested) {
        throw new Error("必须分别确认历史数据授权与逐单元标签复核");
      }
      const created = await createShadowEvaluationManifestV2(
        manifestImport.taskId,
        {
          ...manifestImport.draft,
          operator_attests_authorized_historical_use: true,
          operator_attests_labels_reviewed: true,
        },
      );
      setManifestReceipts((current) =>
        [created, ...current.filter((item) => item.receipt_id !== created.receipt_id)]
          .sort((left, right) => right.created_at.localeCompare(left.created_at)),
      );
      setManifestImport((current) => ({
        ...emptyManifestImport,
        taskId: current.taskId,
      }));
      setFeedback(
        `服务端已从 ${created.labelled_unit_count} 条记录生成 ${created.receipt_id}；误放行 ${created.confusion.false_release_count}、误拦截 ${created.confusion.false_block_count}，Receipt SHA ${created.receipt_sha256}。`,
      );
      try {
        const refreshedSummary = await getProjectGovernanceEffectiveness(
          activeProject?.project_id ?? created.project_id,
        );
        setGovernanceSummary(refreshedSummary);
        setGovernanceSummaryError(undefined);
      } catch (summaryFailure) {
        setGovernanceSummary(undefined);
        setGovernanceSummaryError(
          `回执已封存，但项目级治理汇总刷新失败：${readableError(summaryFailure)}`,
        );
      }
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page-stack">
      <nav className="governance-command-rail system-hub-toolbar" aria-label="治理页面导航">
        <a className="is-active" href="#effectiveness"><BarChart3 size={15} /><span><small>01</small>效果指标</span></a>
        <a href="#private-industrial-validation"><DatabaseZap size={15} /><span><small>LIVE</small>离线工业验证</span></a>
        <a href="#shadow-ledger"><DatabaseZap size={15} /><span><small>02</small>影子回执</span></a>
        <a href="#dynamicbench-evidence"><Fingerprint size={15} /><span><small>REF</small>动态基准</span></a>
        <a href="#release-control"><PackageCheck size={15} /><span><small>03</small>发布门禁</span></a>
        <a href="#audit-control"><Braces size={15} /><span><small>04</small>审计安全</span></a>
        <button type="button" onClick={() => navigate("/evidence")}><FileCheck2 size={15} /><span><small>LIVE</small>查看证据</span><ArrowRight size={13} /></button>
        <button type="button" onClick={() => navigate("/runs")}><Fingerprint size={15} /><span><small>LIVE</small>查看运行</span><ArrowRight size={13} /></button>
        <button type="button" onClick={() => setRefreshToken((value) => value + 1)} disabled={loading || connection.api !== "CONNECTED"}><RefreshCw size={14} />刷新</button>
      </nav>

      <SystemHubHero
        eyebrow="GOVERNANCE / EFFECTIVENESS / RELEASE CONTROL"
        title="治理效果与发布门禁"
        description="把效果测量、影子回执、任务放行和审计安全拆成四条独立但可追溯的治理工作流。"
        ariaLabel="治理工作流"
        meta={<><EvidenceSourceBadge source={connection.api === "CONNECTED" ? "LIVE_API" : "NOT_CONNECTED"} /><span>{activeProject?.name ?? "NO PROJECT"}</span><span>HUMAN AUTHORITY</span></>}
        cards={[
          { id: "effectiveness", eyebrow: "01 · EFFECTIVENESS", title: "治理效果测量", description: "按真实分析单位计算误放行与误拦截。", status: governanceSummary?.measurement_status ?? "NOT MEASURED", tone: "cyan", icon: BarChart3, href: "#effectiveness", members: [
            { icon: ShieldCheck, title: "误放行率", detail: confusionIsGrouped ? "GROUPED BY UNIT" : formatRate(singleConfusionGroup?.false_release_rate) },
            { icon: BarChart3, title: "误拦截率", detail: confusionIsGrouped ? "GROUPED BY UNIT" : formatRate(singleConfusionGroup?.false_block_rate) },
            { icon: FileCheck2, title: "整改后通过", detail: formatRate(governanceSummary?.verified_remediation_pass_rate) },
          ] },
          { id: "shadow", eyebrow: "02 · SHADOW LEDGER", title: "历史影子回执", description: "标签只进入独立评测平面。", status: `${governanceSummary?.receipt_count ?? 0} RECEIPTS`, tone: "violet", icon: DatabaseZap, href: "#shadow-ledger", members: [
            { icon: DatabaseZap, title: "授权历史批次", detail: `${receipts.length + manifestReceipts.length} details loaded` },
            { icon: FileJson, title: "逐单元 Manifest", detail: "SERVER DERIVED V2" },
            { icon: Fingerprint, title: "项目级汇总", detail: governanceSummary ? "SHA BOUND" : "UNAVAILABLE" },
          ] },
          { id: "release", eyebrow: "03 · RELEASE GATE", title: "任务发布门禁", description: "任务完成不等于生产放行。", status: currentReleaseStatus, tone: "coral", icon: PackageCheck, href: "#release-control", members: [
            { icon: FileCheck2, title: "证据完整性", detail: releaseReadiness?.evidence_integrity ?? "UNAVAILABLE" },
            { icon: PackageCheck, title: "开放工单", detail: String(releaseReadiness?.open_work_order_count ?? "UNAVAILABLE") },
            { icon: UserCheck, title: "最终权限", detail: "NAMED HUMAN" },
          ] },
          { id: "audit", eyebrow: "04 · AUDIT SAFETY", title: "审计与失败关闭", description: "缺失证据或权限漂移时拒绝继续。", status: "FAIL CLOSED", tone: "lime", icon: Braces, href: "#audit-control", members: [
            { icon: Braces, title: "RFC 8785 JCS", detail: "规范化完整性链" },
            { icon: KeyRound, title: "Authority Epoch", detail: "过期回执拒绝" },
            { icon: LockKeyhole, title: "设备写入", detail: "false" },
          ] },
        ]}
      />

      <div className="governance-outcome-strip">
        <span><ShieldCheck size={18} /></span>
        <div><small>CURRENT TASK RELEASE READINESS</small><strong>{currentReleaseOutcome}</strong><p>{releaseTask ? `来自最新完成任务 ${releaseTask.task_id} 的实时就绪回执；效果指标不会覆盖任务门禁。` : "当前项目尚无带证据的完成任务；页面保持 NOT MEASURED。"}</p></div>
        <StatusBadge tone={releaseReadiness ? readinessTone(releaseReadiness.overall_status) : "warning"}>{currentReleaseStatus}</StatusBadge>
      </div>

      <PrivateIndustrialValidationPanel
        workspaceId={activeWorkspace?.workspace_id}
        projectId={activeProject?.project_id}
        apiConnected={connection.api === "CONNECTED"}
      />

      <EvaluationEvidencePanel
        id="dynamicbench-evidence"
        surface="governance"
        scope={connection.api === "CONNECTED" && activeWorkspace && activeProject
          ? {
              kind: "PROJECT_REFERENCE",
              workspaceId: activeWorkspace.workspace_id,
              projectId: activeProject.project_id,
            }
          : undefined}
      />

      <div className="metric-grid metric-grid--four" id="effectiveness">
        <Metric
          label="误放行率"
          value={
            loading && !governanceSummary
              ? "LOADING"
              : governanceSummaryError
              ? "UNAVAILABLE"
              : confusionIsGrouped
                ? "GROUPED BY UNIT"
                : formatRate(singleConfusionGroup?.false_release_rate)
          }
          detail={
            confusionIsGrouped
              ? `${governanceSummary.confusion_groups.length} 种分析单元，禁止跨单位合并`
              : singleConfusionGroup
                ? `${singleConfusionGroup.false_release_rate.numerator} / ${singleConfusionGroup.false_release_rate.denominator} · ${singleConfusionGroup.unit_of_analysis}`
                : "后端项目汇总尚无可计算分母"
          }
          tone={
            confusionIsGrouped
              ? "warning"
              : metricTone(singleConfusionGroup?.false_release_rate)
          }
          icon={ShieldCheck}
        />
        <Metric
          label="误拦截率"
          value={
            loading && !governanceSummary
              ? "LOADING"
              : governanceSummaryError
              ? "UNAVAILABLE"
              : confusionIsGrouped
                ? "GROUPED BY UNIT"
                : formatRate(singleConfusionGroup?.false_block_rate)
          }
          detail={
            confusionIsGrouped
              ? `${governanceSummary.confusion_groups.length} 种分析单元，见下方后端分组`
              : singleConfusionGroup
                ? `${singleConfusionGroup.false_block_rate.numerator} / ${singleConfusionGroup.false_block_rate.denominator} · ${singleConfusionGroup.unit_of_analysis}`
                : "后端项目汇总尚无可计算分母"
          }
          tone={
            confusionIsGrouped
              ? "warning"
              : metricTone(singleConfusionGroup?.false_block_rate, "warning")
          }
          icon={BarChart3}
        />
        <Metric
          label="整改后验证通过率"
          value={
            loading && !governanceSummary
              ? "LOADING"
              : governanceSummaryError
              ? "UNAVAILABLE"
              : formatRate(governanceSummary?.verified_remediation_pass_rate)
          }
          detail={
            governanceSummary
              ? `${governanceSummary.verified_remediation_pass_rate.numerator} / ${governanceSummary.verified_remediation_pass_rate.denominator} · 后端同合同复验汇总`
              : "后端项目汇总尚不可用"
          }
          tone={
            governanceSummary?.verified_remediation_pass_rate.status === "MEASURED"
              ? "info"
              : "warning"
          }
          icon={FileCheck2}
        />
        <Metric
          label="整改未决"
          value={
            loading && !governanceSummary
              ? "LOADING"
              : governanceSummaryError
              ? "UNAVAILABLE"
              : formatRate(governanceSummary?.unresolved_remediation_rate)
          }
          detail={
            governanceSummary
              ? `${governanceSummary.unresolved_remediation_rate.numerator} / ${governanceSummary.unresolved_remediation_rate.denominator} · 后端整改尝试汇总`
              : "后端项目汇总尚不可用"
          }
          tone={metricTone(governanceSummary?.unresolved_remediation_rate)}
          icon={DatabaseZap}
        />
      </div>

      {governanceSummaryError ? (
        <div className="shadow-evaluation-notice is-danger">
          {governanceSummaryError} 页面不会回退到浏览器自行聚合。
        </div>
      ) : null}
      {governanceSummary?.confusion_pooling_status === "GROUPED_BY_UNIT" ? (
        <Panel>
          <PanelHeader
            eyebrow="BACKEND-AUTHORITATIVE UNIT GROUPS"
            title="混淆指标按分析单位分组"
            detail="后端已检测到不兼容的分析单位；每组独立计算，页面不提供跨组总值。"
            actions={<StatusBadge tone="warning">GROUPED_BY_UNIT</StatusBadge>}
          />
          <div className="shadow-receipt-list">
            {governanceSummary.confusion_groups.map((group) => (
              <details key={group.group_sha256} open>
                <summary>
                  <span>
                    <strong>{group.unit_of_analysis}</strong>
                    <small>
                      {group.labelled_unit_count} labelled units · {group.receipt_count} receipts
                    </small>
                  </span>
                  <StatusBadge tone="info" compact>
                    UNIT SAFE
                  </StatusBadge>
                </summary>
                <div>
                  <DetailRow
                    label="false release"
                    value={`${formatRate(group.false_release_rate)} · ${group.false_release_rate.numerator}/${group.false_release_rate.denominator}`}
                  />
                  <DetailRow
                    label="false block"
                    value={`${formatRate(group.false_block_rate)} · ${group.false_block_rate.numerator}/${group.false_block_rate.denominator}`}
                  />
                  <DetailRow label="tasks / receipts" value={`${group.task_count} / ${group.receipt_count}`} />
                  <Digest label="Group SHA-256" value={group.group_sha256} />
                </div>
              </details>
            ))}
          </div>
          <Digest label="Project Summary SHA-256" value={governanceSummary.summary_sha256} />
        </Panel>
      ) : null}

      {error ? <div className="shadow-evaluation-notice is-danger">{error}</div> : null}
      {feedback ? <div className="shadow-evaluation-notice is-success">{feedback}</div> : null}

      <div className="governance-grid governance-grid--shadow" id="shadow-ledger">
        <Panel variant="raised">
          <PanelHeader
            eyebrow="AUTHORIZED SHADOW LEDGER"
            title="历史批次影子回执"
            detail="逐任务接口仅用于明细展示；上方指标只来自项目级后端权威汇总。"
            actions={loading ? <LoaderCircle className="is-spinning" size={16} /> : <StatusBadge tone={receipts.length + manifestReceipts.length ? "success" : "warning"} compact>{governanceSummary ? `DETAILS ${receipts.length + manifestReceipts.length}/${governanceSummary.receipt_count}` : "DETAILS UNAVAILABLE"}</StatusBadge>}
          />
          {receipts.length + manifestReceipts.length ? (
            <div className="shadow-receipt-list">
              {manifestReceipts.map((receipt) => (
                <details key={receipt.receipt_id}>
                  <summary>
                    <span><strong>{receipt.identity.batch_alias}</strong><small>{receipt.identity.site_alias} / {receipt.identity.line_alias} / {receipt.identity.camera_alias}</small></span>
                    <StatusBadge tone="success" compact>SERVER DERIVED V2</StatusBadge>
                  </summary>
                  <div>
                    <DetailRow label="task" value={receipt.task_id} />
                    <DetailRow label="labelled units" value={`${receipt.labelled_unit_count} · ${receipt.unit_of_analysis}`} />
                    <DetailRow label="false release" value={`${receipt.confusion.false_release_count}/${receipt.false_release_rate.denominator}`} />
                    <DetailRow label="false block" value={`${receipt.confusion.false_block_count}/${receipt.false_block_rate.denominator}`} />
                    <DetailRow label="server computed counts" value={String(receipt.server_computed_counts)} />
                    <DetailRow label="client aggregate counts accepted" value={String(receipt.client_supplied_aggregate_counts_accepted)} />
                    <Digest label="Evaluation Manifest SHA-256" value={receipt.evaluation_manifest_sha256} />
                    <Digest label="Receipt SHA-256" value={receipt.receipt_sha256} />
                    <small>{receipt.claim_boundary}</small>
                  </div>
                </details>
              ))}
              {receipts.map((receipt) => (
                <details key={receipt.receipt_id}>
                  <summary>
                    <span><strong>{receipt.identity.batch_alias}</strong><small>{receipt.identity.site_alias} / {receipt.identity.line_alias} / {receipt.identity.camera_alias}</small></span>
                    <StatusBadge tone={receipt.measurement_status === "MEASURED" ? "success" : "warning"} compact>LEGACY V1 · {receipt.measurement_status}</StatusBadge>
                  </summary>
                  <div>
                    <DetailRow label="task" value={receipt.task_id} />
                    <DetailRow label="labelled units" value={`${receipt.labelled_unit_count} · ${receipt.confusion.unit_of_analysis}`} />
                    <DetailRow label="false release" value={`${receipt.false_release_rate.numerator}/${receipt.false_release_rate.denominator}`} />
                    <DetailRow label="false block" value={`${receipt.false_block_rate.numerator}/${receipt.false_block_rate.denominator}`} />
                    <DetailRow label="remediation pass" value={`${receipt.verified_remediation_pass_rate.numerator}/${receipt.verified_remediation_pass_rate.denominator}`} />
                    <Digest label="Receipt SHA-256" value={receipt.receipt_sha256} />
                    <small>{receipt.claim_boundary}</small>
                  </div>
                </details>
              ))}
            </div>
          ) : governanceSummary?.receipt_count ? (
            <div className="shadow-evaluation-empty">
              <DatabaseZap size={22} />
              <strong>项目汇总已有 {governanceSummary.receipt_count} 条回执，但明细未完整载入</strong>
              <p>指标仍使用后端项目汇总；请刷新或检查上方明细错误，不会用空明细覆盖汇总。</p>
            </div>
          ) : (
            <div className="shadow-evaluation-empty">
              <DatabaseZap size={22} />
              <strong>尚无授权历史批次影子回执</strong>
              <p>公开 Omni、Synthetic 或页面 fixture 不会自动计入这里。</p>
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            eyebrow="IMPORT / PER-UNIT EVALUATION V2"
            title="导入逐单元影子 Manifest"
            detail="浏览器只上传逐单元 Truth、Gate 与整改证据引用；所有聚合计数和 Manifest SHA 均由服务端生成。"
            actions={
              <ActionButton
                variant="secondary"
                icon={Download}
                onClick={downloadManifestTemplate}
              >
                下载 JSON 模板
              </ActionButton>
            }
          />
          <form className="shadow-evaluation-form" onSubmit={(event) => void submitManifest(event)}>
            <label className="shadow-field shadow-field--wide">
              <span>已完成任务</span>
              <select required value={manifestImport.taskId} onChange={(event) => updateManifestImport("taskId", event.target.value)} disabled={submitting || !eligibleTasks.length}>
                {!eligibleTasks.length ? <option value="">当前项目无可登记任务</option> : null}
                {eligibleTasks.map((task) => <option value={task.task_id} key={task.task_id}>{task.goal} · {task.task_id}</option>)}
              </select>
            </label>
            <label className="shadow-field shadow-field--wide">
              <span>本地逐单元 JSON Manifest</span>
              <input
                type="file"
                accept="application/json,.json"
                onChange={(event) => void importManifestFile(event)}
                disabled={submitting}
              />
            </label>
            {manifestImport.draft ? (
              <div className="shadow-manifest-preview">
                <div>
                  <FileJson size={20} />
                  <span><strong>{manifestImport.fileName}</strong><small>LOCAL VALIDATED · NOT SUBMITTED</small></span>
                </div>
                <DetailRow label="batch" value={manifestImport.draft.identity.batch_alias} />
                <DetailRow label="site / line / camera" value={`${manifestImport.draft.identity.site_alias} / ${manifestImport.draft.identity.line_alias} / ${manifestImport.draft.identity.camera_alias}`} />
                <DetailRow label="unit_of_analysis" value={manifestImport.draft.unit_of_analysis} />
                <DetailRow label="per-unit rows" value={manifestImport.draft.units.length} />
                <DetailRow label="ground truth" value={manifestImport.draft.ground_truth_method} />
                <small>页面未接收或计算 confusion count、rate、Truth Manifest SHA、Gate Manifest SHA；这些字段只能来自服务端回执。</small>
              </div>
            ) : (
              <div className="shadow-evaluation-empty">
                <FileJson size={22} />
                <strong>尚未导入逐单元 Manifest</strong>
                <p>模板中的证据 SHA 占位符必须替换为真实的逐单元外部证据摘要。</p>
              </div>
            )}
            <label className="shadow-attestation"><input type="checkbox" checked={manifestImport.authorizedAttested} onChange={(event) => updateManifestImport("authorizedAttested", event.target.checked)} /><span>我确认该历史批次用途已获授权；数据仅用于本地只读影子评测。</span></label>
            <label className="shadow-attestation"><input type="checkbox" checked={manifestImport.labelsReviewedAttested} onChange={(event) => updateManifestImport("labelsReviewedAttested", event.target.checked)} /><span>我确认逐单元 Truth、Gate 与整改证据引用已经人工复核。</span></label>
            <button className="shadow-submit" type="submit" disabled={submitting || !manifestImport.taskId || !manifestImport.draft || !manifestImport.authorizedAttested || !manifestImport.labelsReviewedAttested || connection.api !== "CONNECTED"}>
              {submitting ? <LoaderCircle className="is-spinning" size={14} /> : <Fingerprint size={14} />}
              {submitting ? "正在请求服务端重算并封存…" : "提交逐单元记录并生成 V2 回执"}
            </button>
          </form>
        </Panel>
      </div>

      <ClaimBoundary title="指标证据边界" tone="warning">
        上方指标只读取后端项目级哈希汇总；不同分析单元只分组展示，绝不在浏览器跨回执或跨单位相加。它不与 Synthetic、Omni 公共 Pilot 或 DynamicBench 混成总准确率，操作者声明与 SHA 绑定也不等于独立客户验收。
      </ClaimBoundary>

      <div className="governance-grid" id="release-control">
        <Panel variant="raised">
          <PanelHeader eyebrow="LIVE TASK RELEASE GATE" title="当前任务发布就绪" detail={releaseTask ? `${releaseTask.goal} · ${releaseTask.task_id}` : "等待当前项目产生带证据的完成任务。"} />
          {releaseReadiness ? (
            <div className="release-gates">
              {releaseReadiness.checks.map((check, index) => (
                <article key={check.key} title={check.summary}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{check.label}</strong>
                  <StatusBadge tone={readinessCheckTone(check.status)}>{check.status}</StatusBadge>
                </article>
              ))}
            </div>
          ) : (
            <div className="shadow-evaluation-empty">
              <PackageCheck size={22} />
              <strong>发布就绪尚不可读取</strong>
              <p>{releaseError ?? "需要已完成且已封存证据的真实任务。"}</p>
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHeader eyebrow="AUTHORITY MATRIX" title="角色权限" detail="Reviewer 和模型都没有写权限。" />
          <div className="authority-matrix">
            <div className="authority-matrix__header"><span>Capability</span><span>Operator</span><span>Reviewer</span><span>Agent</span></div>
            {[
              ["读取 evidence", "ALLOW", "ALLOW", "SCOPED"],
              ["创建 Gate Run", "CONDITIONAL", "DENY", "DENY"],
              ["登记影子标签摘要", "NAMED HUMAN", "DENY", "DENY"],
              ["批准 CAPA", "NAMED HUMAN", "DENY", "DENY"],
              ["执行派生版本", "CONDITIONAL", "DENY", "DENY"],
              ["生产放行", "EXTERNAL AUTHORITY", "DENY", "DENY"],
              ["设备写入", "DENY", "DENY", "DENY"],
            ].map(([capability, operator, reviewer, agent]) => (
              <div key={capability}><strong>{capability}</strong><span>{operator}</span><span>{reviewer}</span><span>{agent}</span></div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="governance-grid governance-grid--audit" id="audit-control">
        <Panel>
          <PanelHeader eyebrow="AUDIT ENVELOPE" title="规范化完整性链" detail="组件摘要、血缘、具名决定与权限 epoch。" />
          <div className="governance-audit-flow">
            <span><Braces size={18} /> RFC 8785 JCS</span>
            <span><FileCheck2 size={18} /> component digests</span>
            <span><KeyRound size={18} /> authority epoch</span>
            <strong><ShieldCheck size={19} /> Case Audit Root</strong>
          </div>
          {releaseReadiness ? <Digest label="Readiness Report SHA-256 · live" value={releaseReadiness.report_sha256} /> : null}
          {releaseReadiness?.evidence_sha256 ? <Digest label="Evidence ZIP SHA-256 · live task" value={releaseReadiness.evidence_sha256} /> : <DetailRow label="Evidence ZIP SHA-256" value="UNAVAILABLE" />}
          <ClaimBoundary title="密码学边界" tone="info">tamper-evident，不是数字签名、可信时间戳或外部锚。</ClaimBoundary>
        </Panel>

        <Panel>
          <PanelHeader eyebrow="RUNTIME SAFETY" title="失败关闭控制" detail="缺失证据、失效权限或状态漂移不会静默重放。" />
          <div className="safety-controls">
            <DetailRow label="production_release_allowed" value={<StatusBadge tone="danger">false</StatusBadge>} />
            <DetailRow label="machine_write_permitted" value={<StatusBadge tone="danger">false</StatusBadge>} />
            <DetailRow label="shadow labels enter Agent core" value={<StatusBadge tone="locked">false</StatusBadge>} />
            <DetailRow label="raw image transmission" value={<StatusBadge tone="locked">false</StatusBadge>} />
            <DetailRow label="stale Worker receipt" value="REJECT · STALE_AUTHORITY_EPOCH" />
            <DetailRow label="uncertain command" value="NO AUTO REPLAY" />
          </div>
        </Panel>
      </div>

      <div className="platform-contracts">
        <article><span><LockKeyhole size={19} /></span><strong>Development</strong><p>PRIVATE · not frozen</p></article>
        <article><span><PackageCheck size={19} /></span><strong>SBOM</strong><p>CycloneDX 1.6</p></article>
        <article><span><Fingerprint size={19} /></span><strong>Attestation</strong><p>UNSIGNED</p></article>
        <article><span><UserCheck size={19} /></span><strong>Production authority</strong><p>HUMAN ONLY</p></article>
      </div>

      <ClaimBoundary title="最终发布结论" tone="danger">
        {currentReleaseStatus} / {currentReleaseOutcome}：任务就绪回执只决定是否可进入具名人工复核；不等于生产放行、客户验收、发行构包或官方提交完成。
      </ClaimBoundary>
    </div>
  );
}
