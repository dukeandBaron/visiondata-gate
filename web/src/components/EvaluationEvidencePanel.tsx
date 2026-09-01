import {
  ArrowRight,
  FileCheck2,
  Fingerprint,
  GitBranch,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Workflow,
} from "lucide-react";
import { useEffect, useState } from "react";
import { getDynamicBenchEvaluationEvidence } from "../data/evaluationEvidenceApi";
import type {
  DynamicBenchEvaluationEvidenceProjection,
  DynamicBenchReportEvidence,
  EvaluationEvidenceRequestScope,
} from "../evaluationEvidenceDomain";
import { Digest, Panel, PanelHeader, StatusBadge } from "./ui";

type LoadingState = "IDLE" | "LOADING" | "READY" | "UNAVAILABLE";

interface EvaluationEvidencePanelProps {
  id?: string;
  scope?: EvaluationEvidenceRequestScope;
  surface?: "review" | "governance";
}

function scopeKey(scope: EvaluationEvidenceRequestScope | undefined): string {
  if (!scope) return "NO_SCOPE";
  if (scope.kind === "GLOBAL_REVIEW") return scope.kind;
  if (scope.kind === "WORKSPACE_REFERENCE") return `${scope.kind}:${scope.workspaceId}`;
  return `${scope.kind}:${scope.workspaceId}:${scope.projectId}`;
}

function compactSha(value: string | null): string {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "UNAVAILABLE";
}

function percent(value: number): string {
  return `${(value * 100).toFixed(value === 0 || value === 1 ? 0 : 1)}%`;
}

function reportTone(report: DynamicBenchReportEvidence): "success" | "danger" {
  return report.availability === "AVAILABLE" && report.verification_status === "VERIFIED"
    ? "success"
    : "danger";
}

function scopeLabel(projection: DynamicBenchEvaluationEvidenceProjection): string {
  switch (projection.scope.scope_kind) {
    case "GLOBAL_REVIEW":
      return "GLOBAL FROZEN REFERENCE";
    case "WORKSPACE_REFERENCE":
      return `WORKSPACE REFERENCE · ${projection.scope.workspace_id}`;
    case "PROJECT_REFERENCE":
      return `PROJECT REFERENCE · ${projection.scope.project_id}`;
  }
}

function ReportUnavailable({ report }: { report: DynamicBenchReportEvidence }) {
  return (
    <div className="evaluation-evidence__report-unavailable" role="status">
      <TriangleAlert size={18} aria-hidden="true" />
      <div>
        <strong>UNAVAILABLE · FAILED CLOSED</strong>
        <span>{report.verification_error_code ?? "REPORT_NOT_VERIFIED"}</span>
      </div>
    </div>
  );
}

export function EvaluationEvidencePanel({
  id = "dynamicbench-evidence",
  scope,
  surface = "review",
}: EvaluationEvidencePanelProps) {
  const [refreshToken, setRefreshToken] = useState(0);
  const [state, setState] = useState<LoadingState>(scope ? "LOADING" : "IDLE");
  const [projection, setProjection] =
    useState<DynamicBenchEvaluationEvidenceProjection>();
  const [error, setError] = useState<string>();
  const currentScopeKey = scopeKey(scope);

  useEffect(() => {
    let current = true;
    if (!scope) {
      setState("IDLE");
      setProjection(undefined);
      setError("未绑定可见工作空间；冻结基准不会跨作用域补位。");
      return () => {
        current = false;
      };
    }
    setState("LOADING");
    setProjection(undefined);
    setError(undefined);
    void getDynamicBenchEvaluationEvidence(scope)
      .then((next) => {
        if (!current) return;
        setProjection(next);
        setState("READY");
      })
      .catch((caught: unknown) => {
        if (!current) return;
        setProjection(undefined);
        setState("UNAVAILABLE");
        setError(caught instanceof Error ? caught.message : "只读评测证据未通过前端合同核验");
      });
    return () => {
      current = false;
    };
  }, [currentScopeKey, refreshToken]);

  const v3 = projection?.reports[0];
  const v4 = projection?.reports[1];
  const v3Metrics = v3?.core_metrics;
  const v4Metrics = v4?.core_metrics;
  const panelStatus = projection?.status ?? "HOLD";
  const unavailable = state === "IDLE" || state === "UNAVAILABLE";

  return (
    <Panel
      id={id}
      className={`evaluation-evidence evaluation-evidence--${surface}${unavailable ? " evaluation-evidence--unavailable" : ""}`}
      variant="raised"
      dataStatus={state === "LOADING" ? "VERIFYING" : unavailable ? "HOLD" : panelStatus}
    >
      <PanelHeader
        eyebrow="EVALUATION PLANE · READ ONLY"
        title="DynamicBench 编排证据"
        detail="v3 比较冻结合成编排；v4 核验 ProductService / Incident v6 真实代码路径。两条证据不可合并为工厂性能。"
        actions={(
          <div className="evaluation-evidence__actions">
            <StatusBadge
              tone={state === "LOADING" ? "neutral" : panelStatus === "PASS_LOCAL_EVIDENCE" ? "success" : "danger"}
              compact
            >
              {state === "LOADING" ? "VERIFYING" : unavailable ? "HOLD · UNAVAILABLE" : panelStatus}
            </StatusBadge>
            <button
              type="button"
              onClick={() => setRefreshToken((value) => value + 1)}
              disabled={!scope || state === "LOADING"}
              aria-label="重新核验 DynamicBench 只读证据"
            >
              {state === "LOADING" ? <LoaderCircle className="is-spinning" size={14} /> : <RefreshCw size={14} />}
              <span>重新核验</span>
            </button>
          </div>
        )}
      />

      {state === "LOADING" ? (
        <div className="evaluation-evidence__loading" role="status" aria-live="polite">
          <LoaderCircle className="is-spinning" size={18} />
          <span><strong>正在重新核验两份冻结报告</strong>只有 schema、作用域、边界与双 SHA 全部一致才展示指标。</span>
        </div>
      ) : unavailable ? (
        <div className="evaluation-evidence__failure" role="alert">
          <TriangleAlert size={20} aria-hidden="true" />
          <div>
            <strong>HOLD · EVALUATION EVIDENCE UNAVAILABLE</strong>
            <p>{error ?? "只读评测证据不可用。"}</p>
            <small>页面不使用 fixture、文档数字或浏览器计算结果补位。</small>
          </div>
        </div>
      ) : projection && v3 && v4 ? (
        <>
          <div className="evaluation-evidence__scope" aria-label="评测证据作用域">
            <LockKeyhole size={15} aria-hidden="true" />
            <strong>{scopeLabel(projection)}</strong>
            <span>{projection.scope.association_status}</span>
            <em><ShieldCheck size={14} /> PAYLOAD SHA + ETAG VERIFIED</em>
          </div>

          <div className="evaluation-evidence__track" aria-label="DynamicBench v3 与 v4 独立证据轨">
            <article className="evaluation-evidence__report" data-version="v3">
              <header>
                <span className="evaluation-evidence__version">v3</span>
                <div>
                  <small>FROZEN SYNTHETIC</small>
                  <h3>动态编排 vs 固定规则</h3>
                </div>
                <StatusBadge tone={reportTone(v3)} compact>{v3.verification_status}</StatusBadge>
              </header>
              {v3Metrics ? (
                <>
                  <div className="evaluation-evidence__primary-comparison">
                    <div>
                      <small>FIXED RULE · CORRECT TERMINAL</small>
                      <strong>{v3Metrics.fixed_rule_correct_terminal_disposition_count}<i>/</i>{v3Metrics.fixture_denominator}</strong>
                    </div>
                    <ArrowRight size={19} aria-hidden="true" />
                    <div>
                      <small>DYNAMIC · CORRECT TERMINAL</small>
                      <strong>{v3Metrics.dynamic_replanning_correct_terminal_disposition_count}<i>/</i>{v3Metrics.fixture_denominator}</strong>
                    </div>
                  </div>
                  <dl className="evaluation-evidence__metrics">
                    <div><dt>工具调用 · 动态 / 固定</dt><dd>{v3Metrics.dynamic_replanning_total_tool_call_count} / {v3Metrics.fixed_rule_total_tool_call_count}</dd></div>
                    <div><dt>无效调用减少</dt><dd>{v3Metrics.unnecessary_tool_call_reduction_count}</dd></div>
                    <div><dt>工具故障恢复 · 动态 / 固定</dt><dd>{percent(v3Metrics.dynamic_replanning_tool_failure_recovery_rate)} / {percent(v3Metrics.fixed_rule_tool_failure_recovery_rate)}</dd></div>
                    <div><dt>真实模型调用</dt><dd>{v3Metrics.actual_model_call_count}</dd></div>
                  </dl>
                </>
              ) : <ReportUnavailable report={v3} />}
              <details>
                <summary><Fingerprint size={14} /> 查看 v3 工件绑定</summary>
                <span>{v3.source_artifact_name}</span>
                <code>{compactSha(v3.sealed_report_sha256)}</code>
              </details>
            </article>

            <div className="evaluation-evidence__seam" aria-label="证据不可合并">
              <span>≠</span>
              <small>NOT<br />POOLED</small>
            </div>

            <article className="evaluation-evidence__report" data-version="v4">
              <header>
                <span className="evaluation-evidence__version">v4</span>
                <div>
                  <small>REAL CODE PATH · SYNTHETIC INPUT</small>
                  <h3>ProductService → Incident v6</h3>
                </div>
                <StatusBadge tone={reportTone(v4)} compact>{v4.verification_status}</StatusBadge>
              </header>
              {v4Metrics ? (
                <>
                  <div className="evaluation-evidence__runtime-route">
                    <Workflow size={18} aria-hidden="true" />
                    <code>{v4.production_route}</code>
                  </div>
                  <dl className="evaluation-evidence__metrics">
                    <div><dt>ProductService 执行通过</dt><dd>{v4Metrics.passed_count}/{v4Metrics.fixed_fixture_denominator}</dd></div>
                    <div><dt>Incident v6 工件</dt><dd>{v4Metrics.incident_v6_count}/{v4Metrics.product_service_execution_count}</dd></div>
                    <div><dt>DecisionPacket v3</dt><dd>{v4Metrics.decision_packet_v3_count}/{v4Metrics.product_service_execution_count}</dd></div>
                    <div><dt>故障后失败关闭恢复</dt><dd>{v4Metrics.tool_failure_recovered_fail_closed_count}/{v4Metrics.tool_failure_fixture_count}</dd></div>
                  </dl>
                </>
              ) : <ReportUnavailable report={v4} />}
              <details>
                <summary><Fingerprint size={14} /> 查看 v4 工件绑定</summary>
                <span>{v4.source_artifact_name}</span>
                <code>{compactSha(v4.sealed_report_sha256)}</code>
              </details>
            </article>
          </div>

          <div className="evaluation-evidence__boundary" role="note">
            <div>
              <TriangleAlert size={17} aria-hidden="true" />
              <span><strong>不是工厂性能</strong>{projection.factory_metrics_status}</span>
            </div>
            <div><FileCheck2 size={16} /><span><strong>真实影子指标</strong>{projection.factory_shadow_metrics_status}</span></div>
            <div><GitBranch size={16} /><span><strong>客户验证</strong>{projection.customer_validation_status}</span></div>
            <div><LockKeyhole size={16} /><span><strong>生产放行</strong>{String(projection.production_release_allowed)}</span></div>
          </div>
          <p className="evaluation-evidence__truth-isolation">
            benchmark truth feedback to Agent runtime = {String(projection.benchmark_truth_feedback_to_agent_runtime)} · machine write = {String(projection.machine_write_permitted)}
          </p>
          <Digest label="EVALUATION PROJECTION SHA-256" value={projection.projection_sha256} />
        </>
      ) : null}
    </Panel>
  );
}
