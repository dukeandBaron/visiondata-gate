import {
  Braces,
  CircleOff,
  DatabaseZap,
  Factory,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { useEffect, useState } from "react";
import { getPrivateIndustrialValidationSummary } from "../data/privateIndustrialValidationApi";
import { OperatorApiError } from "../data/api";
import type {
  IndustrialValidationRateMetric,
  IndustrialValidationScenarioGroupName,
  IndustrialValidationStrategy,
  PrivateIndustrialValidationSummary,
} from "../privateIndustrialValidationDomain";
import {
  ActionButton,
  ClaimBoundary,
  Digest,
  Metric,
  Panel,
  PanelHeader,
  StatusBadge,
} from "./ui";
import "../styles/private-industrial-validation.css";

interface PrivateIndustrialValidationPanelProps {
  workspaceId?: string;
  projectId?: string;
  apiConnected: boolean;
}

interface LoadFailure {
  code: string;
  message: string;
  status?: number;
}

const scenarioLabels: Record<IndustrialValidationScenarioGroupName, string> = {
  NORMAL_NO_FAULT: "正常 · 无故障",
  TRANSIENT_RECOVERABLE_FAULT: "瞬态 · 可恢复故障",
  PERSISTENT_FAULT_SAFETY_COST: "持续故障 · 安全代价",
};

const strategyLabels: Record<IndustrialValidationStrategy, string> = {
  FIXED_SINGLE_ATTEMPT: "固定单次",
  FIXED_UNIFORM_BOUNDED_RETRY: "固定统一重试",
  DYNAMIC_CONTRACT_AWARE_RETRY: "动态合同感知重试",
};

function readableRate(metric: IndustrialValidationRateMetric): string {
  if (metric.status !== "MEASURED" || metric.value === null) {
    return metric.status.replaceAll("_", " ");
  }
  return `${(metric.value * 100).toFixed(1)}% · ${metric.numerator}/${metric.denominator}`;
}

function failureFrom(error: unknown): LoadFailure {
  if (error instanceof OperatorApiError) {
    return { code: error.code, message: error.message, status: error.status };
  }
  return {
    code: "INDUSTRIAL_VALIDATION_UNKNOWN_FAILURE",
    message: error instanceof Error ? error.message : "私有工业验证摘要读取失败",
  };
}

export function PrivateIndustrialValidationPanel({
  workspaceId,
  projectId,
  apiConnected,
}: PrivateIndustrialValidationPanelProps) {
  const [summary, setSummary] = useState<PrivateIndustrialValidationSummary>();
  const [failure, setFailure] = useState<LoadFailure>();
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setSummary(undefined);
    setFailure(undefined);
    if (!workspaceId || !projectId) {
      setFailure({
        code: "INDUSTRIAL_VALIDATION_SCOPE_MISSING",
        message: "未选择工作区或项目，不能读取项目作用域的私有工业验证摘要。",
      });
      return () => {
        active = false;
      };
    }
    if (!apiConnected) {
      setFailure({
        code: "LOCAL_API_UNAVAILABLE",
        message: "本地 API 未连接；页面不会使用 fixture 或嵌入数字补位。",
      });
      return () => {
        active = false;
      };
    }
    setLoading(true);
    void getPrivateIndustrialValidationSummary(workspaceId, projectId)
      .then((value) => {
        if (!active) return;
        setSummary(value);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setFailure(failureFrom(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [apiConnected, attempt, projectId, workspaceId]);

  const retry = () => setAttempt((current) => current + 1);

  if (loading) {
    return (
      <Panel id="private-industrial-validation" variant="raised">
        <PanelHeader
          eyebrow="PRIVATE INDUSTRIAL VALIDATION"
          title="正在核验离线工业验证摘要"
          detail="读取项目作用域 API，并复算 JCS SHA-256、ETag 与内容摘要。"
          actions={<LoaderCircle className="is-spinning" size={18} />}
        />
        <div className="private-validation-loading" role="status">
          <DatabaseZap size={22} />
          <span>NO FIXTURE FALLBACK · NO EMBEDDED METRICS</span>
        </div>
      </Panel>
    );
  }

  if (failure || !summary) {
    const currentFailure = failure ?? {
      code: "INDUSTRIAL_VALIDATION_UNAVAILABLE",
      message: "私有工业验证摘要不可用。",
    };
    return (
      <Panel id="private-industrial-validation" variant="danger">
        <PanelHeader
          eyebrow="PRIVATE INDUSTRIAL VALIDATION"
          title="离线工业验证摘要失败关闭"
          detail="404、503、网络故障或合同漂移均不会回退到浏览器历史数字。"
          actions={<StatusBadge tone="danger">HOLD</StatusBadge>}
        />
        <div className="private-validation-failure" role="alert">
          <CircleOff size={22} />
          <div>
            <strong>{currentFailure.code}</strong>
            <p>{currentFailure.message}</p>
            {currentFailure.status !== undefined ? <small>HTTP {currentFailure.status}</small> : null}
          </div>
          <ActionButton variant="secondary" icon={RefreshCw} onClick={retry}>
            重新读取并核验
          </ActionButton>
        </div>
      </Panel>
    );
  }

  if (
    summary.verification_status === "FAILED_CLOSED" ||
    summary.visa_public_proxy === null
  ) {
    return (
      <Panel id="private-industrial-validation" variant="danger">
        <PanelHeader
          eyebrow="PRIVATE INDUSTRIAL VALIDATION"
          title="后端摘要已验证，但证据投影保持失败关闭"
          detail={summary.availability}
          actions={<StatusBadge tone="danger">HOLD</StatusBadge>}
        />
        <div className="private-validation-failure" role="alert">
          <ShieldAlert size={22} />
          <div>
            <strong>{summary.failure_codes.join(" · ") || "FAILED_CLOSED"}</strong>
            <p>投影本身通过 SHA 绑定；内部证据缺失或漂移，因此页面不显示历史指标。</p>
          </div>
          <ActionButton variant="secondary" icon={RefreshCw} onClick={retry}>
            重新读取并核验
          </ActionButton>
        </div>
        <Digest label="Projection SHA-256" value={summary.projection_sha256} />
      </Panel>
    );
  }

  const visa = summary.visa_public_proxy;
  const omni = summary.omni_offline_validation;
  const factoryMetrics = summary.factory_shadow_metrics;

  return (
    <Panel id="private-industrial-validation" variant="raised">
      <PanelHeader
        eyebrow="PRIVATE INDUSTRIAL VALIDATION · LIVE API"
        title="离线数据集证据与工厂影子真值严格分轨"
        detail={`${summary.scope.scope_kind} · ${summary.scope.association_status}`}
        actions={(
          <div className="private-validation-actions">
            <StatusBadge tone="warning">{summary.status}</StatusBadge>
            <ActionButton variant="ghost" icon={RefreshCw} onClick={retry}>重新核验</ActionButton>
          </div>
        )}
      />

      <div className="metric-grid metric-grid--four private-validation-metrics">
        <Metric label="证据可用性" value={summary.availability} detail="RC5 current + Omni historical" tone="warning" icon={DatabaseZap} />
        <Metric label="当前环境复验" value={visa.recomputable_now ? "TRUE" : "FALSE"} detail={visa.evidence_origin} tone="success" icon={Braces} />
        <Metric label="工厂真值" value="NOT MEASURED" detail={factoryMetrics.evidence_origin} tone="danger" icon={Factory} />
        <Metric label="生产放行" value="FALSE" detail="human authority remains required" tone="danger" icon={ShieldAlert} />
      </div>

      <div className="private-validation-hold-reasons" role="status">
        <ShieldAlert size={17} />
        <strong>HOLD REASONS</strong>
        <span>{summary.failure_codes.join(" · ") || "NO_ADDITIONAL_FAILURE_CODE"}</span>
      </div>

      <div className="private-validation-tracks">
        <article>
          <header><small>{visa.evidence_track}</small><StatusBadge tone="info">{visa.status}</StatusBadge></header>
          <strong>VisA 公开工业代理 · RC5 当前环境复验</strong>
          <p><b>evidence_origin</b> {visa.evidence_origin}</p>
          <p><b>recomputable_now</b> {visa.recomputable_now ? "TRUE" : "FALSE"}</p>
          <p><b>actual_factory_truth</b> FALSE</p>
          <small>{visa.dynamic_capability_claim}</small>
        </article>
        <article>
          <header><small>{omni.evidence_track}</small><StatusBadge tone="warning">{omni.status}</StatusBadge></header>
          <strong>Omni 私有数据集离线验证</strong>
          <p>{omni.fixed_gate_sample_count} 个固定门禁样本 · finding {omni.parent_finding_count} → {omni.child_finding_count}（{omni.finding_count_delta}）</p>
          <p>已核责任关闭 {omni.verified_closed_responsibility_count} · 仍开放 {omni.open_responsibility_count}</p>
          <small>factory_shadow_equivalent=FALSE · production_release_allowed=FALSE</small>
        </article>
        <article data-tone="hold">
          <header><small>{factoryMetrics.evidence_track}</small><StatusBadge tone="danger">HOLD</StatusBadge></header>
          <strong>{factoryMetrics.status}</strong>
          <p><b>evidence_origin</b> {factoryMetrics.evidence_origin}</p>
          <p>误放行 {readableRate(factoryMetrics.false_release_rate)}</p>
          <p>误拦截 {readableRate(factoryMetrics.false_block_rate)}</p>
          <p>整改后通过 {readableRate(factoryMetrics.remediation_pass_rate)}</p>
          <small>{factoryMetrics.false_release_rate.not_measured_reason_code}</small>
        </article>
      </div>

      <section className="private-validation-scenarios" aria-label="VisA 三类故障场景策略对照">
        <header>
          <div><small>PROGRAMMATIC GOVERNANCE TRUTH</small><strong>正常、瞬态与持续故障分组</strong></div>
          <span>RC5 当前环境已重算 · 600 episodes · 非工厂真值</span>
        </header>
        {visa.scenario_groups.map((group) => (
          <article key={group.scenario_group}>
            <div className="private-validation-scenarios__label">
              <small>{group.scenario_group}</small>
              <strong>{scenarioLabels[group.scenario_group]}</strong>
              <span>{group.episode_denominator} episodes · {group.fault_modes.join(" / ") || "NO FAULT"}</span>
            </div>
            <div className="private-validation-strategies">
              {group.strategies.map((strategy) => (
                <div key={strategy.execution_strategy}>
                  <strong>{strategyLabels[strategy.execution_strategy]}</strong>
                  <span>正确 {readableRate(strategy.correct_decision_rate)}</span>
                  <span>误放 {readableRate(strategy.false_release_rate)}</span>
                  <span>误拦 {readableRate(strategy.false_block_rate)}</span>
                  <code>{strategy.physical_tool_call_count} calls · {strategy.retry_count} retries</code>
                </div>
              ))}
            </div>
          </article>
        ))}
      </section>

      <div className="private-validation-digests">
        <Digest label="Projection SHA-256" value={summary.projection_sha256} />
        <Digest label={`${visa.compact_receipt_artifact_name} file SHA-256`} value={visa.compact_receipt_file_sha256} />
        <Digest label="VisA compact receipt SHA-256" value={visa.compact_receipt_sha256} />
        <Digest label="VisA benchmark report SHA-256" value={visa.benchmark_report_sha256} />
      </div>
      <ClaimBoundary title="DATASET_OFFLINE_VALIDATION ≠ FACTORY_SHADOW_METRICS" tone="danger">
        {summary.claim_boundary}
      </ClaimBoundary>
    </Panel>
  );
}
