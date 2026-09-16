import {
  Bot,
  Check,
  CircleDashed,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { StatusTone } from "../domain";
import { StatusBadge } from "./ui";

export type TaskResponsibilityState = "OBSERVED" | "WAITING" | "UNKNOWN";

export interface TaskResponsibilityItem {
  id: "agent" | "tool" | "human" | "readback";
  label: string;
  state: TaskResponsibilityState;
  summary: string;
  detail: string;
  href: string;
}

const responsibilityIcons = {
  agent: Bot,
  tool: Wrench,
  human: UserCheck,
  readback: ShieldCheck,
};

function responsibilityTone(state: TaskResponsibilityState): StatusTone {
  if (state === "OBSERVED") return "info";
  if (state === "WAITING") return "warning";
  return "locked";
}

export function TaskResponsibilityRail({ items }: { items: TaskResponsibilityItem[] }) {
  return (
    <nav className="finals-task-rail" aria-label="当前任务责任分工">
      {items.map((item) => {
        const Icon = responsibilityIcons[item.id];
        return (
          <Link className={`finals-task-rail__item is-${item.state.toLowerCase()}`} to={item.href} key={item.id}>
            <span className="finals-task-rail__label"><Icon size={13} />{item.label}</span>
            <strong>{item.summary || "UNKNOWN"}</strong>
            <small>{item.detail}</small>
            <StatusBadge tone={responsibilityTone(item.state)} compact>{item.state}</StatusBadge>
          </Link>
        );
      })}
    </nav>
  );
}

export type CapaRequestReadbackPhase =
  | "NOT_REQUESTED"
  | "REQUEST_UNKNOWN"
  | "SERVER_VERIFIED"
  | "READBACK_VERIFIED";

const capaReadbackSteps = [
  { phase: "NOT_REQUESTED", label: "NOT REQUESTED" },
  { phase: "REQUEST_UNKNOWN", label: "REQUEST SENT / UNKNOWN" },
  { phase: "SERVER_VERIFIED", label: "SERVER VERIFIED" },
  { phase: "READBACK_VERIFIED", label: "CHILD / OUTCOME READBACK" },
] as const;

export function CapaRequestReadbackRail({ phase }: { phase: CapaRequestReadbackPhase }) {
  const currentIndex = capaReadbackSteps.findIndex((item) => item.phase === phase);
  return (
    <section className={`capa-readback-rail is-${phase.toLowerCase()}`} aria-label="CAPA 写入与结果回读状态">
      <ol>
        {capaReadbackSteps.map((item, index) => (
          <li
            className={index < currentIndex ? "is-complete" : index === currentIndex ? "is-current" : ""}
            key={item.phase}
          >
            <i>{index < currentIndex ? <Check size={10} /> : index === currentIndex ? <CircleDashed size={10} /> : index + 1}</i>
            <span>{item.label}</span>
          </li>
        ))}
      </ol>
      <p>{phase === "REQUEST_UNKNOWN"
        ? "不得自动重放写请求；只允许 GET 对账。"
        : phase === "READBACK_VERIFIED"
          ? "服务端记录与 Child / Outcome 回读均已核验；生产放行仍为 false。"
          : phase === "SERVER_VERIFIED"
            ? "CAPA 已由服务端回读确认；继续等待 Child / Outcome 对账。"
            : "尚未发起受控 CAPA 写入。"}</p>
    </section>
  );
}

export type RunRecoveryState = "WAITING" | "UNKNOWN" | "BLOCKED" | "HUMAN_REVIEW";

function recoveryTone(state: RunRecoveryState): StatusTone {
  if (state === "BLOCKED") return "danger";
  if (state === "UNKNOWN") return "locked";
  return "warning";
}

export function RunRecoveryRail({
  state,
  title,
  detail,
  actionLabel,
  href,
  onAction,
}: {
  state: RunRecoveryState;
  title: string;
  detail: string;
  actionLabel: string;
  href?: string;
  onAction?: () => void;
}) {
  const action = href
    ? <Link to={href}>{actionLabel}</Link>
    : <button type="button" onClick={onAction}><RefreshCw size={12} />{actionLabel}</button>;
  return (
    <section className={`run-recovery-rail is-${state.toLowerCase()}`} aria-label="当前任务恢复动作" role="status">
      <StatusBadge tone={recoveryTone(state)} compact>{state === "HUMAN_REVIEW" ? "HUMAN REVIEW" : state}</StatusBadge>
      <div><strong>{title}</strong><small>{detail}</small></div>
      {action}
    </section>
  );
}
