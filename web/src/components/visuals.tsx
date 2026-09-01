import {
  ArrowDown,
  ArrowRight,
  Bot,
  Box,
  Check,
  ChevronDown,
  CircleDot,
  FileCheck2,
  Folder,
  FolderOpen,
  GitBranch,
  Image as ImageIcon,
  LockKeyhole,
  ScanSearch,
  ShieldCheck,
  UserCheck,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { cases, lineage, toolReceipts } from "../data/fixtures";
import type { CaseRecord, LineageNode } from "../domain";
import { EvidenceSourceBadge, StatusBadge } from "./ui";

function gateTone(status: CaseRecord["status"]) {
  if (status === "PASS" || status === "PASS_LOCAL") return "success" as const;
  if (status === "RECAPTURE") return "warning" as const;
  if (status === "HOLD" || status === "TRANSFERRED_TO_INVESTIGATION") return "danger" as const;
  return "neutral" as const;
}

export function CaseTree({ activeCaseId = "rc3-omni-05" }: { activeCaseId?: string }) {
  const active = cases.find((item) => item.id === activeCaseId);
  const parent = cases.find((item) => item.id === "rc3-omni-03");
  const child = cases.find((item) => item.id === "rc3-omni-05");
  if (!active || !parent || !child) return null;

  if (!active.id.startsWith("rc3-omni")) {
    return (
      <div className="case-tree" aria-label="案件资产树">
        <div className="tree-row tree-row--root">
          <FolderOpen size={16} aria-hidden="true" />
          <strong>VisionData Gate</strong>
        </div>
        <div className="tree-branch">
          <div className="tree-row">
            <Box size={15} aria-hidden="true" />
            <span>{active.dataset}</span>
            <small>{active.namespace}</small>
          </div>
          <div className="tree-branch">
            <div className="tree-row is-active">
              <FileCheck2 size={15} aria-hidden="true" />
              <span>{active.displayId}</span>
              <StatusBadge tone={gateTone(active.status)} compact>
                {active.status}
              </StatusBadge>
            </div>
            <div className="tree-branch tree-branch--assets">
              <div className="tree-row">
                <ImageIcon size={14} aria-hidden="true" />
                <span>Frozen evidence</span>
                <small>aggregate-only</small>
              </div>
            </div>
          </div>
        </div>
        <div className="case-tree__summary">
          <span>当前责任底账</span>
          <strong>{active.responsibilityClosed} closed / {active.responsibilityOpen} open</strong>
          <small>{active.workOrders ?? 0} work orders · production false</small>
        </div>
      </div>
    );
  }

  return (
    <div className="case-tree" aria-label="案件资产树">
      <div className="tree-row tree-row--root">
        <FolderOpen size={16} aria-hidden="true" />
        <strong>VisionData Gate</strong>
      </div>
      <div className="tree-branch">
        <div className="tree-row">
          <Box size={15} aria-hidden="true" />
          <span>Omni RC3</span>
          <small>authorized</small>
        </div>
        <div className="tree-branch">
          <div className={`tree-row${activeCaseId === parent.id ? " is-active" : ""}`}>
            <FileCheck2 size={15} aria-hidden="true" />
            <span>{parent.displayId}</span>
            <StatusBadge tone={gateTone(parent.status)} compact>
              RECAPTURE
            </StatusBadge>
          </div>
          <div className={`tree-row${activeCaseId === child.id ? " is-active" : ""}`}>
            <GitBranch size={15} aria-hidden="true" />
            <span>{child.displayId}</span>
            <StatusBadge tone={gateTone(child.status)} compact>
              HOLD
            </StatusBadge>
          </div>
          <div className="tree-branch tree-branch--assets">
            <div className="tree-row">
              <Folder size={14} aria-hidden="true" />
              <span>Private derived</span>
              <small>180 / 60</small>
            </div>
            <div className="tree-row">
              <ImageIcon size={14} aria-hidden="true" />
              <span>Evidence refs</span>
              <small>hash-bound</small>
            </div>
          </div>
        </div>
      </div>
      <div className="case-tree__summary">
        <span>当前责任底账</span>
        <strong>{active.responsibilityClosed} closed / {active.responsibilityOpen} open</strong>
        <small>不是 49 个 Agent 任务</small>
      </div>
    </div>
  );
}

export function InspectionCanvas({ compact = false, caseRecord }: { compact?: boolean; caseRecord?: CaseRecord }) {
  const [view, setView] = useState<"before" | "derived">("before");
  const before = view === "before";
  const syntheticCase = caseRecord?.id === "synthetic-v3";
  const derivedPin = syntheticCase
    ? "PASS_LOCAL"
    : caseRecord
      ? caseRecord.status
      : "Child: 33 findings";
  const derivedBoundary = syntheticCase
    ? "Synthetic-v3 固定修复复验 · PASS / F1 1.00"
    : "Omni 聚合状态，不构造图像效果指标";
  return (
    <div className={`inspection${compact ? " is-compact" : ""}`}>
      <div className="inspection__toolbar">
        <div className="segmented" aria-label="视觉证据视图">
          <button type="button" className={before ? "is-active" : ""} onClick={() => setView("before")}>
            Before
          </button>
          <button type="button" className={!before ? "is-active" : ""} onClick={() => setView("derived")}>
            Derived
          </button>
        </div>
        <span className="inspection__label">
          <ScanSearch size={14} aria-hidden="true" />
          SYNTHETIC VISUAL SLOT
        </span>
      </div>
      <div className={`inspection__stage${before ? " is-before" : " is-derived"}`}>
        <svg viewBox="0 0 760 430" role="img" aria-label="合成视觉证据示意，不是真实工厂图像">
          <defs>
            <linearGradient id="surface" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor={before ? "#202d36" : "#27353c"} />
              <stop offset="0.5" stopColor={before ? "#111a21" : "#17252a"} />
              <stop offset="1" stopColor={before ? "#2d3740" : "#2e3d43"} />
            </linearGradient>
            <filter id="softness">
              <feGaussianBlur stdDeviation={before ? "5" : "1.2"} />
            </filter>
          </defs>
          <rect x="12" y="12" width="736" height="406" rx="20" fill="#080e13" stroke="#314452" />
          <rect x="46" y="44" width="668" height="332" rx="48" fill="url(#surface)" stroke="#65737b" />
          <g filter="url(#softness)" opacity="0.95">
            <ellipse cx="240" cy="205" rx="136" ry="92" fill="#10161a" stroke="#8b969a" strokeWidth="8" />
            <circle cx="240" cy="205" r="48" fill="#3b4649" stroke="#b0b9ba" strokeWidth="10" />
            <circle cx="240" cy="205" r="17" fill="#11171a" />
            <rect x="430" y="124" width="150" height="160" rx="22" fill="#1a2429" stroke="#a6b0b2" strokeWidth="7" />
            <path d="M463 172h84M463 204h84M463 236h84" stroke="#67767a" strokeWidth="12" />
          </g>
          <rect
            x={before ? "128" : "148"}
            y={before ? "112" : "126"}
            width={before ? "210" : "182"}
            height={before ? "182" : "158"}
            rx="6"
            fill="none"
            stroke={before ? "#ff5d5d" : "#45d794"}
            strokeWidth="4"
          />
          <path
            d={before ? "M338 112h58l24-24" : "M330 126h66l24-24"}
            fill="none"
            stroke={before ? "#ff5d5d" : "#45d794"}
            strokeWidth="3"
          />
          <rect x="408" y="60" width="220" height="58" rx="9" fill="#091018" stroke={before ? "#ff5d5d" : "#45d794"} />
          <text x="426" y="84" fill={before ? "#ff7c75" : "#61e5a5"} fontSize="14" fontFamily="ui-monospace, monospace">
            {before ? "LOW_SHARPNESS" : "DERIVED VISUAL"}
          </text>
          <text x="426" y="103" fill="#9ba9b2" fontSize="12" fontFamily="ui-monospace, monospace">
            {before ? "Laplacian 1.8585 < 18" : "no PASS claim from image alone"}
          </text>
          <text x="48" y="404" fill="#60717c" fontSize="12" fontFamily="ui-monospace, monospace">
            embedded synthetic fallback · not a factory image · not an effect claim
          </text>
        </svg>
        <div className="inspection__pin">
          <span>{before ? "FAIL" : syntheticCase ? "FIXTURE RECHECK" : "NO IMAGE PASS CLAIM"}</span>
          <strong>{before ? "1.8585" : derivedPin}</strong>
        </div>
      </div>
      <div className="inspection__footer">
        <EvidenceSourceBadge source="FROZEN_FIXTURE" />
        <span>{before ? "Synthetic-v3 单一已验证测量" : derivedBoundary}</span>
      </div>
    </div>
  );
}

const incidentGraphNodes = [
  { label: "Intake", detail: "contract freeze", state: "complete" },
  { label: "Deterministic tools", detail: "5 families", state: "complete" },
  { label: "Dynamic replan", detail: "evidence triggered", state: "active" },
  { label: "Policy Judge", detail: "fail closed", state: "complete" },
  { label: "Human gate", detail: "production locked", state: "blocked" },
] as const;

const syntheticGraphNodes = [
  { label: "Injected truth", detail: "12 bounded issues", state: "complete" },
  { label: "Deterministic tools", detail: "same contract", state: "complete" },
  { label: "Controlled repair", detail: "fixture only", state: "complete" },
  { label: "Independent recheck", detail: "F1 1.00", state: "complete" },
  { label: "Production gate", detail: "still locked", state: "blocked" },
] as const;

export function ToolGraph({ vertical = false, mode = "incident" }: { vertical?: boolean; mode?: "incident" | "synthetic" }) {
  const graphNodes = mode === "synthetic" ? syntheticGraphNodes : incidentGraphNodes;
  return (
    <div className={`tool-graph${vertical ? " is-vertical" : ""}`}>
      {graphNodes.map((node, index) => (
        <div className="tool-graph__segment" key={node.label}>
          <div className={`tool-node tool-node--${node.state}`}>
            <span className="tool-node__icon">
              {node.state === "complete" ? (
                <Check size={15} />
              ) : node.state === "active" ? (
                <Workflow size={15} />
              ) : (
                <LockKeyhole size={15} />
              )}
            </span>
            <strong>{node.label}</strong>
            <small>{node.detail}</small>
          </div>
          {index < graphNodes.length - 1 ? (
            vertical ? (
              <ArrowDown className="tool-graph__arrow" size={17} />
            ) : (
              <ArrowRight className="tool-graph__arrow" size={17} />
            )
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function AgentTrace({ caseRecord }: { caseRecord?: CaseRecord }) {
  const [expanded, setExpanded] = useState(true);
  const syntheticCase = caseRecord?.id === "synthetic-v3";
  const publicPilot = caseRecord?.id === "omni-180-rc2";
  return (
    <div className="agent-trace">
      <div className="agent-trace__controller">
        <span className="agent-trace__icon">
          <Bot size={18} />
        </span>
        <div>
          <span>Agent Controller</span>
          <strong>{syntheticCase ? "Deterministic Recheck" : "Dynamic Leader"}</strong>
        </div>
        <StatusBadge tone="info" compact>
          {syntheticCase ? "FIXTURE" : "GATED"}
        </StatusBadge>
      </div>
      <div className="phase-strip">
        {syntheticCase ? (
          <>
            <span className="is-complete">1 真值</span>
            <span className="is-complete">2 修复</span>
            <span className="is-complete">3 复验</span>
            <span className="is-blocked">4 生产</span>
          </>
        ) : publicPilot ? (
          <>
            <span className="is-complete">1 取证</span>
            <span className="is-complete">2 重规划</span>
            <span className="is-active">3 裁决</span>
            <span className="is-blocked">4 放行</span>
          </>
        ) : (
          <>
            <span className="is-complete">1 取证</span>
            <span className="is-complete">2 重规划</span>
            <span className="is-active">3 人工</span>
            <span className="is-blocked">4 放行</span>
          </>
        )}
      </div>
      <button className="trace-summary" type="button" onClick={() => setExpanded((value) => !value)}>
        <span>
          <CircleDot size={14} /> 结构化决策摘要
        </span>
        <ChevronDown className={expanded ? "is-expanded" : ""} size={16} />
      </button>
      {expanded ? (
        <div className="trace-summary__body">
          {syntheticCase ? (
            <>
              <p>12 个合成注入真值问题按同一固定合同完成修复与独立复验。</p>
              <p>PASS / F1 1.00 只属于 Synthetic-v3，不能外推为真实工厂效果。</p>
            </>
          ) : publicPilot ? (
            <>
              <p>固定 180 张公开样本触发 1 次重规划和 3 个只读 Worker。</p>
              <p>最终 45 findings / 45 work orders，裁决保持 RECAPTURE。</p>
            </>
          ) : (
            <>
              <p>中间证据改变下一步补证任务，触发 1 次重规划和 3 个只读 Worker。</p>
              <p>Child Run 后仍有 43 条责任项打开，Policy Judge 保持失败关闭。</p>
            </>
          )}
          <small>不展示模型私有思维链；实际外部模型调用为 0。</small>
        </div>
      ) : null}
      <div className="receipt-mini-list">
        {syntheticCase ? (
          <>
            <div><span>TRUTH</span><strong>12 injected issues</strong><StatusBadge tone="success" compact>VERIFIED</StatusBadge></div>
            <div><span>RECHECK</span><strong>same-contract fixture</strong><StatusBadge tone="success" compact>PASS_LOCAL</StatusBadge></div>
          </>
        ) : publicPilot ? (
          <>
            <div><span>PILOT</span><strong>180 frozen images</strong><StatusBadge tone="success" compact>COMPLETED</StatusBadge></div>
            <div><span>REPLAN</span><strong>1 / 3 Workers</strong><StatusBadge tone="success" compact>COMPLETED</StatusBadge></div>
            <div><span>GATE</span><strong>45 findings / orders</strong><StatusBadge tone="warning" compact>RECAPTURE</StatusBadge></div>
          </>
        ) : (
          toolReceipts.slice(0, 4).map((receipt) => (
            <div key={receipt.id}>
              <span>{receipt.id}</span>
              <strong>{receipt.tool}</strong>
              <StatusBadge tone={receipt.state === "COMPLETED" ? "success" : "locked"} compact>
                {receipt.state}
              </StatusBadge>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function lineageIcon(kind: LineageNode["kind"]) {
  if (kind === "HUMAN_DECISION") return UserCheck;
  if (kind === "DERIVED") return Box;
  if (kind === "CHILD") return GitBranch;
  if (kind === "OUTCOME") return LockKeyhole;
  return FileCheck2;
}

export function LineageGraph({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`lineage-graph${compact ? " is-compact" : ""}`}>
      {lineage.map((node, index) => {
        const Icon = lineageIcon(node.kind);
        return (
          <div className="lineage-graph__segment" key={node.id}>
            <article className={`lineage-node lineage-node--${node.kind.toLowerCase()}`}>
              <span className="lineage-node__icon">
                <Icon size={17} />
              </span>
              <small>{node.kind.replaceAll("_", " ")}</small>
              <strong>{node.label}</strong>
              <StatusBadge tone={node.kind === "OUTCOME" ? "danger" : node.kind === "HUMAN_DECISION" ? "warning" : "info"} compact>
                {node.state}
              </StatusBadge>
              <p>{node.detail}</p>
            </article>
            {index < lineage.length - 1 ? (
              <div className="lineage-edge">
                <span />
                <ArrowRight size={15} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function HumanGateBar({ reviewer = false }: { reviewer?: boolean }) {
  return (
    <div className="human-gate">
      <div className="human-gate__status">
        <span className="human-gate__lock">
          <LockKeyhole size={18} />
        </span>
        <div>
          <small>HUMAN GATE BAR</small>
          <strong>拒绝生产放行</strong>
        </div>
        <StatusBadge tone="danger">LOCKED</StatusBadge>
      </div>
      <button type="button" disabled>
        <ShieldCheck size={16} />
        {reviewer ? "Reviewer 无批准权限" : "批准 CAPA 并派生 Child Case"}
      </button>
      <p>{reviewer ? "只读页面不会发送写请求。" : "需要具名人工、有效审批绑定与可执行状态；当前 fixture 禁止写操作。"}</p>
    </div>
  );
}
