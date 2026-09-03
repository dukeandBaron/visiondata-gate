import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileKey2,
  ImageOff,
  LockKeyhole,
  ShieldX,
} from "lucide-react";
import { useEffect, useId, useState } from "react";
import type {
  CausalReplayReport,
  CausalReplayStep,
  EvidenceSource,
  StatusTone,
} from "../domain";
import { EvidenceSourceBadge, StatusBadge } from "./ui";

export type CausalReplayViewState = "FROZEN" | "LOADING" | "READY" | "ERROR";

export interface CausalReplayBinding {
  parentTaskId: string;
  capaCaseId: string;
}

interface CausalReplayProps {
  report: CausalReplayReport | null;
  source: EvidenceSource;
  state: CausalReplayViewState;
  binding?: CausalReplayBinding;
  errorMessage?: string;
}

const frozenStepLabels = [
  ["T0", "NOT_EVALUATED"],
  ["T1", "等待哈希绑定回放"],
  ["T2", "等待哈希绑定回放"],
  ["T3", "等待哈希绑定回放"],
  ["T4", "等待哈希绑定回放"],
] as const;

function statusTone(status: CausalReplayStep["status"]): StatusTone {
  if (status === "COMPLETED") return "success";
  if (status === "BLOCKED") return "danger";
  return "warning";
}

function statusIcon(status: CausalReplayStep["status"]) {
  if (status === "COMPLETED") return CheckCircle2;
  if (status === "BLOCKED") return ShieldX;
  return Clock3;
}

function optionalCount(value: number | null): string {
  return value === null ? "NOT_EVALUATED" : String(value);
}

function FrozenReplay({
  state,
  binding,
  errorMessage,
}: Pick<CausalReplayProps, "state" | "binding" | "errorMessage">) {
  const isLoading = state === "LOADING";
  const isError = state === "ERROR";
  const heading = isLoading
    ? "正在读取 SHA 绑定回放"
    : isError
      ? "真实回放不可用"
      : "未绑定真实 Parent Task / CAPA Case";
  const description = isLoading
    ? "只有响应通过只读合同、T0–T4 顺序、请求绑定与 SHA 格式校验后，页面才会切换为 LIVE API。"
    : isError
      ? "请求失败后保持 NOT CONNECTED；不会用冻结 fixture 替代真实响应。"
      : "未提供可验证的 tsk_* 与 capa_* 绑定时，不推测阶段计数或伪造证据引用；页面数据源标签保持显式。";

  return (
    <div className="causal-replay causal-replay--empty" aria-live="polite">
      <div className={`causal-replay__notice${isError ? " is-error" : ""}`} role={isError ? "alert" : "status"}>
        {isLoading ? <Clock3 size={16} className="is-spinning" aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
        <div>
          <strong>{heading}</strong>
          <p>{description}</p>
          {binding ? (
            <code>{binding.parentTaskId} / {binding.capaCaseId}</code>
          ) : null}
          {errorMessage ? <small>{errorMessage}</small> : null}
        </div>
      </div>

      <div className="causal-replay__frozen-rail" aria-label="冻结回放占位，未加载真实阶段数据">
        {frozenStepLabels.map(([stepId, label], index) => (
          <div key={stepId} className={index === 0 ? "is-current" : ""}>
            <span>{stepId}</span>
            <small>{label}</small>
          </div>
        ))}
      </div>

      <div className="causal-replay__empty-grid">
        <div className="causal-replay__binding-help">
          <FileKey2 size={18} aria-hidden="true" />
          <div>
            <strong>真实回放接入条件</strong>
            <p>使用页面查询参数 <code>parentTaskId</code> 与 <code>capaCaseId</code> 绑定已封存的产品任务。</p>
          </div>
        </div>
        <UnauthorizedImagePlaceholder />
      </div>
    </div>
  );
}

function UnauthorizedImagePlaceholder() {
  return (
    <div className="causal-replay__image-placeholder" role="img" aria-label="无授权工厂图像，因果回放仅展示证据引用">
      <ImageOff size={22} aria-hidden="true" />
      <strong>NO AUTHORIZED IMAGE</strong>
      <small>不以 Synthetic SVG 或示意图冒充真实工厂原图</small>
    </div>
  );
}

export function CausalReplay({ report, source, state, binding, errorMessage }: CausalReplayProps) {
  const detailId = useId();
  const [activeSequence, setActiveSequence] = useState(0);

  useEffect(() => {
    if (!report) {
      setActiveSequence(0);
      return;
    }
    const currentSequence = report.steps.findIndex(
      (step) => step.step_id === report.current_step_id,
    );
    setActiveSequence(currentSequence >= 0 ? currentSequence : 0);
  }, [report]);

  if (state !== "READY" || !report) {
    return (
      <FrozenReplay
        state={state}
        binding={binding}
        errorMessage={errorMessage}
      />
    );
  }

  const activeStep = report.steps[activeSequence] ?? report.steps[0];
  if (!activeStep) return null;
  const ActiveStatusIcon = statusIcon(activeStep.status);
  const responsibilityEvaluated =
    activeStep.responsibility_closed !== null || activeStep.responsibility_open !== null;
  const responsibilityClosed = activeStep.responsibility_closed ?? 0;
  const responsibilityOpen = activeStep.responsibility_open ?? 0;
  const responsibilityDenominator = responsibilityClosed + responsibilityOpen;

  return (
    <div className="causal-replay">
      <div className="causal-replay__control">
        <div className="causal-replay__control-meta">
          <div>
            <EvidenceSourceBadge source={source} />
            <StatusBadge tone="locked" compact><LockKeyhole size={11} aria-hidden="true" /> READ ONLY</StatusBadge>
          </div>
          <small>键盘 ← → / Home / End 切换阶段</small>
        </div>
        <input
          className="causal-replay__range"
          type="range"
          min={0}
          max={report.steps.length - 1}
          step={1}
          value={activeSequence}
          aria-label="T0 到 T4 因果回放阶段"
          aria-valuetext={`${activeStep.step_id} ${activeStep.label}`}
          aria-controls={detailId}
          onChange={(event) => setActiveSequence(Number(event.currentTarget.value))}
        />
        <div className="causal-replay__steps" aria-label="因果回放阶段导航">
          {report.steps.map((step) => {
            const StepIcon = statusIcon(step.status);
            const isActive = step.sequence === activeSequence;
            return (
              <button
                key={step.step_id}
                type="button"
                className={isActive ? "is-active" : ""}
                aria-current={isActive ? "step" : undefined}
                aria-label={`${step.step_id} ${step.label}，${step.status}`}
                onClick={() => setActiveSequence(step.sequence)}
              >
                <span><StepIcon size={13} aria-hidden="true" /> {step.step_id}</span>
                <small>{step.label}</small>
              </button>
            );
          })}
        </div>
      </div>

      <section id={detailId} className="causal-replay__detail" aria-live="polite" aria-label={`${activeStep.step_id} 阶段详情`}>
        <header>
          <div>
            <span>{activeStep.step_id} · SEQ {activeStep.sequence}</span>
            <h3>{activeStep.label}</h3>
            <p>{activeStep.summary}</p>
          </div>
          <StatusBadge tone={statusTone(activeStep.status)}>
            <ActiveStatusIcon size={13} aria-hidden="true" /> {activeStep.status}
          </StatusBadge>
        </header>

        <div className="causal-replay__metrics">
          <article>
            <span>Finding 分母</span>
            <strong>{optionalCount(activeStep.finding_count)}</strong>
            <small>仅统计本阶段独立测量结果</small>
          </article>
          <article>
            <span>责任项分母</span>
            <strong>{responsibilityEvaluated ? responsibilityDenominator : "NOT_EVALUATED"}</strong>
            <small>{responsibilityEvaluated ? `${responsibilityClosed} closed / ${responsibilityOpen} open` : "不与 finding 数合并"}</small>
          </article>
          <article>
            <span>Work Orders</span>
            <strong>{optionalCount(activeStep.work_order_count)}</strong>
            <small>整改交付物，不等同 finding</small>
          </article>
          <article>
            <span>Dynamic Workers</span>
            <strong>{optionalCount(activeStep.dynamic_worker_count)}</strong>
            <small>{activeStep.regressed_atomic_finding_count === null ? "无次生缺陷计数" : `次生原子 finding ${activeStep.regressed_atomic_finding_count}`}</small>
          </article>
        </div>

        <div className="causal-replay__detail-grid">
          <div className="causal-replay__evidence">
            <div>
              <span>ACTOR</span>
              <strong>{activeStep.actor}</strong>
              <small>{activeStep.decision ?? "DECISION_NOT_EVALUATED"}</small>
            </div>
            <div>
              <span>EVIDENCE REFS</span>
              <ul>
                {activeStep.evidence_refs.map((reference) => (
                  <li key={reference}><code>{reference}</code></li>
                ))}
              </ul>
            </div>
            <details>
              <summary>查看证据摘要 SHA ({Object.keys(activeStep.evidence_digests).length})</summary>
              {Object.entries(activeStep.evidence_digests).length > 0 ? (
                <dl>
                  {Object.entries(activeStep.evidence_digests).map(([name, digest]) => (
                    <div key={name}>
                      <dt>{name}</dt>
                      <dd><code>{digest}</code></dd>
                    </div>
                  ))}
                </dl>
              ) : <p>该阶段没有已发生证据摘要。</p>}
            </details>
          </div>
          <UnauthorizedImagePlaceholder />
        </div>
      </section>

      <footer className="causal-replay__footer">
        <div>
          <span>Parent <code>{report.parent_task_id}</code></span>
          <span>CAPA <code>{report.capa_case_id}</code></span>
          <span>Child <code>{report.child_task_id ?? "PENDING"}</code></span>
        </div>
        <code title={report.report_sha256}>report sha256 · {report.report_sha256}</code>
        <p>{report.claim_boundary}</p>
      </footer>
    </div>
  );
}
