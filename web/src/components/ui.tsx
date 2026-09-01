import {
  AlertTriangle,
  ArrowRight,
  Check,
  Copy,
  LockKeyhole,
  ShieldAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import type { EvidenceSource, StatusTone } from "../domain";

const sourceLabels: Record<EvidenceSource, string> = {
  LIVE_API: "LIVE API",
  FROZEN_FIXTURE: "FROZEN FIXTURE",
  LOCAL_CONTRACT: "LOCAL CONTRACT",
  NOT_CONNECTED: "NOT CONNECTED",
};

export function StatusBadge({
  children,
  tone = "neutral",
  compact = false,
}: {
  children: ReactNode;
  tone?: StatusTone;
  compact?: boolean;
}) {
  return (
    <span className={`status-badge status-badge--${tone}${compact ? " is-compact" : ""}`}>
      {children}
    </span>
  );
}

export function EvidenceSourceBadge({ source }: { source: EvidenceSource }) {
  const tone: StatusTone =
    source === "LIVE_API"
      ? "success"
      : source === "FROZEN_FIXTURE"
        ? "info"
        : source === "LOCAL_CONTRACT"
          ? "warning"
          : "locked";
  return (
    <StatusBadge tone={tone} compact>
      {sourceLabels[source]}
    </StatusBadge>
  );
}

export function Panel({
  children,
  className = "",
  id,
  variant = "default",
  dataStatus,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
  variant?: "default" | "raised" | "danger" | "subtle";
  dataStatus?: string;
}) {
  return <section className={`panel panel--${variant} ${className}`.trim()} id={id} data-status={dataStatus}>{children}</section>;
}

export function PanelHeader({
  eyebrow,
  title,
  detail,
  actions,
}: {
  eyebrow?: string;
  title: string;
  detail?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="panel-header">
      <div>
        {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        <h2>{title}</h2>
        {detail ? <p>{detail}</p> : null}
      </div>
      {actions ? <div className="panel-header__actions">{actions}</div> : null}
    </header>
  );
}

export function PageIntro({
  eyebrow,
  title,
  description,
  meta,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-intro">
      <div className="page-intro__copy">
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
        {meta ? <div className="page-intro__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-intro__actions">{actions}</div> : null}
    </div>
  );
}

export interface SystemHubCard {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  status: string;
  tone: "cyan" | "violet" | "coral" | "lime";
  icon: LucideIcon;
  actionLabel?: string;
  href?: string;
  onClick?: () => void;
  members: Array<{
    icon: LucideIcon;
    title: string;
    detail: string;
  }>;
}

export function SystemHubHero({
  eyebrow,
  title,
  description,
  meta,
  cards,
  ariaLabel,
}: {
  eyebrow: string;
  title: string;
  description: string;
  meta?: ReactNode;
  cards: SystemHubCard[];
  ariaLabel: string;
}) {
  return (
    <section className="system-hub-hero">
      <header className="integration-hub-heading system-hub-heading">
        <div>
          <span>{eyebrow}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {meta ? <div className="integration-hub-heading__status">{meta}</div> : null}
      </header>

      <div className="integration-workflow-grid system-hub-grid" aria-label={ariaLabel}>
        {cards.map((card) => {
          const Icon = card.icon;
          const action = <>{card.actionLabel ?? "打开分区"} <ArrowRight size={15} /></>;
          return (
            <article className={`integration-workflow-card system-hub-card is-${card.tone}`} key={card.id}>
              <div className="integration-workflow-card__backdrop"><span>✦</span><i /><i /><i /></div>
              <header>
                <span className="integration-workflow-card__icon"><Icon size={19} /></span>
                <div><small>{card.eyebrow}</small><h2>{card.title}</h2></div>
                <em>{card.status}</em>
              </header>
              <p>{card.description}</p>
              <div className="integration-workflow-members">
                {card.members.map((member) => {
                  const MemberIcon = member.icon;
                  return <div key={member.title}><span><MemberIcon size={15} /></span><div><strong>{member.title}</strong><small>{member.detail}</small></div></div>;
                })}
              </div>
              {card.onClick ? <button type="button" onClick={card.onClick}>{action}</button> : <a className="system-hub-card__link" href={card.href ?? "#"}>{action}</a>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function Metric({
  label,
  value,
  detail,
  tone = "neutral",
  icon: Icon,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: StatusTone;
  icon?: LucideIcon;
}) {
  return (
    <div className={`metric metric--${tone}`}>
      <div className="metric__label">
        {Icon ? <Icon size={15} aria-hidden="true" /> : null}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function ClaimBoundary({
  children,
  tone = "warning",
  title = "证据边界",
}: {
  children: ReactNode;
  tone?: "warning" | "danger" | "info";
  title?: string;
}) {
  const Icon = tone === "danger" ? ShieldAlert : AlertTriangle;
  return (
    <aside className={`claim-boundary claim-boundary--${tone}`}>
      <Icon size={17} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </aside>
  );
}

export function ActionButton({
  children,
  variant = "primary",
  icon: Icon,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  icon?: LucideIcon;
}) {
  return (
    <button className={`action-button action-button--${variant}`} type="button" {...props}>
      {Icon ? <Icon size={16} aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
}

export function LockedAction({
  label,
  reason,
  danger = false,
}: {
  label: string;
  reason: string;
  danger?: boolean;
}) {
  return (
    <div className="locked-action">
      <ActionButton variant={danger ? "danger" : "secondary"} icon={LockKeyhole} disabled>
        {label}
      </ActionButton>
      <small>{reason}</small>
    </div>
  );
}

export function Digest({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="digest">
      <span>{label}</span>
      <code title={value}>{value}</code>
      <button type="button" onClick={copy} aria-label={`复制 ${label}`}>
        {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
      </button>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon">
        <Icon size={21} aria-hidden="true" />
      </div>
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}

export function DetailRow({
  label,
  value,
  trailing,
}: {
  label: string;
  value: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      <strong>{value}</strong>
      {trailing ? <div>{trailing}</div> : null}
    </div>
  );
}

export function StepLink({
  index,
  title,
  detail,
  state,
  last = false,
}: {
  index: number;
  title: string;
  detail: string;
  state: "complete" | "active" | "blocked" | "pending";
  last?: boolean;
}) {
  return (
    <div className={`step-link step-link--${state}`}>
      <span className="step-link__index">{state === "complete" ? <Check size={14} /> : index}</span>
      <div>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
      {!last ? <ArrowRight className="step-link__arrow" size={15} aria-hidden="true" /> : null}
    </div>
  );
}

export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : undefined;
    const dialog = dialogRef.current;
    dialog?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
      )];
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <h2>{title}</h2>
          <button type="button" onClick={onClose} aria-label="关闭">
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
