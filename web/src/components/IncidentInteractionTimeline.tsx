import {
  Bot,
  CheckCircle2,
  GitBranch,
  LockKeyhole,
  UserRound,
} from "lucide-react";
import type {
  IncidentInteractionReceipt,
  IncidentInteractionTurn,
  IncidentQuestionDisposition,
} from "../agentDomain";
import { ActionButton, ClaimBoundary, Digest, StatusBadge } from "./ui";
import "../styles/incident-interaction.css";

interface IncidentInteractionTimelineProps {
  receipt: IncidentInteractionReceipt;
  onOpenParent?: () => void;
  onOpenChild?: () => void;
}

const actionLabels: Record<string, string> = {
  PAUSE_FOR_STRUCTURED_HUMAN_INPUT: "Agent 暂停并提出结构化问题",
  CONTINUE_HOLD: "具名人工决定继续 HOLD",
  ESCALATE_INVESTIGATION: "具名人工决定升级调查",
  SELECT_REMEDIATION_PLAN: "具名人工选择整改方案",
  REQUEST_REVERIFICATION: "具名人工请求复验",
  REJECT_RECOMMENDATION: "具名人工拒绝建议",
  RESUME_WITH_BOUND_DECISION: "Agent 绑定决定后恢复运行",
};

const dispositionLabels: Record<IncidentQuestionDisposition, string> = {
  ANSWERED_BY_ADMITTED_EVIDENCE: "由新证据回答",
  SATISFIED_BY_NAMED_HUMAN_DECISION: "由具名人工决定满足",
  REMAINS_OPEN: "仍未解决",
};

function turnTone(turn: IncidentInteractionTurn): "success" | "warning" | "info" {
  if (turn.actor_kind === "HUMAN") return "warning";
  return turn.sequence === 3 ? "success" : "info";
}

export function IncidentInteractionTimeline({
  receipt,
  onOpenParent,
  onOpenChild,
}: IncidentInteractionTimelineProps) {
  return (
    <section className="interaction-receipt" aria-labelledby="interaction-receipt-title">
      <header className="interaction-receipt__header">
        <div>
          <span>AGENT ↔ HUMAN · OBSERVABLE RECEIPT</span>
          <h2 id="interaction-receipt-title">三轮受控交互</h2>
          <p>暂停、具名决定与恢复均来自服务端不可变回执；不展示隐藏思维链。</p>
        </div>
        <StatusBadge
          tone={receipt.remaining_open_question_count ? "warning" : "success"}
          compact
        >
          {receipt.interaction_status}
        </StatusBadge>
      </header>

      <ol className="interaction-receipt__timeline" aria-label="三轮交互时间线">
        {receipt.turns.map((turn) => {
          const Icon = turn.actor_kind === "HUMAN" ? UserRound : Bot;
          return (
            <li key={turn.sequence} data-actor={turn.actor_kind.toLowerCase()}>
              <div className="interaction-receipt__rail" aria-hidden="true">
                <span>{String(turn.sequence).padStart(2, "0")}</span>
              </div>
              <div className="interaction-receipt__turn">
                <div className="interaction-receipt__turn-title">
                  <Icon size={18} aria-hidden="true" />
                  <strong>{actionLabels[turn.action] ?? turn.action}</strong>
                  <StatusBadge tone={turnTone(turn)} compact>{turn.actor_kind}</StatusBadge>
                </div>
                <p>{turn.actor_id}</p>
                <small>
                  {turn.input_refs.length} 输入引用 · {turn.output_refs.length} 输出引用 · observable only
                </small>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="interaction-receipt__metrics" aria-label="交互问题处置统计">
        <article>
          <span>证据回答</span>
          <strong>{receipt.answered_by_evidence_count}</strong>
          <small>admitted evidence</small>
        </article>
        <article>
          <span>人工决定</span>
          <strong>{receipt.satisfied_by_human_decision_count}</strong>
          <small>named human</small>
        </article>
        <article data-open={receipt.remaining_open_question_count > 0}>
          <span>仍未解决</span>
          <strong>{receipt.remaining_open_question_count}</strong>
          <small>remain fail-closed</small>
        </article>
      </div>

      {receipt.question_resolutions.length ? (
        <div className="interaction-receipt__questions">
          {receipt.question_resolutions.map((question) => (
            <article key={question.question_id}>
              {question.disposition === "REMAINS_OPEN"
                ? <LockKeyhole size={16} aria-hidden="true" />
                : <CheckCircle2 size={16} aria-hidden="true" />}
              <div>
                <strong>{question.expected_evidence_type}</strong>
                <small>{question.question_id}</small>
              </div>
              <StatusBadge
                tone={question.disposition === "REMAINS_OPEN" ? "warning" : "success"}
                compact
              >
                {dispositionLabels[question.disposition]}
              </StatusBadge>
            </article>
          ))}
        </div>
      ) : null}

      <div className="interaction-receipt__actions">
        {onOpenParent ? (
          <ActionButton variant="secondary" icon={GitBranch} onClick={onOpenParent}>
            查看 Parent Case
          </ActionButton>
        ) : null}
        {onOpenChild ? (
          <ActionButton variant="secondary" icon={GitBranch} onClick={onOpenChild}>
            查看 Child Case
          </ActionButton>
        ) : null}
      </div>

      <Digest label="INTERACTION RECEIPT SHA-256" value={receipt.receipt_sha256} />
      <ClaimBoundary title="交互权限边界" tone="warning">
        该回执只证明可观察的暂停、具名人工决定与恢复。自由文本不会自动成为证据；
        production release = false，machine write = false。
      </ClaimBoundary>
    </section>
  );
}
