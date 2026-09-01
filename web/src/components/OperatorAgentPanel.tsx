import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  ClipboardCheck,
  Copy,
  ExternalLink,
  FileCheck2,
  ListChecks,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  Play,
  RotateCcw,
  Send,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type {
  OperatorAgentEvent,
  OperatorAgentEventStage,
  OperatorAnalysisRun,
  OperatorCopilotTurn,
  OperatorImageAsset,
} from "../operatorDomain";

export type AgentPanelView =
  | "OVERVIEW"
  | "PLAN"
  | "TRACE"
  | "KNOWLEDGE"
  | "DELIVERY"
  | "COPILOT";

type TraceFilter = "ALL" | "TOOL" | "KNOWLEDGE" | "DELIVERY" | "HUMAN_GATE";

const quickQuestions = [
  "这张图有哪些可核验证据？",
  "是否存在重复或泄漏风险？",
  "下一步应该怎么处理？",
];

const panelViews: Array<{ key: AgentPanelView; label: string }> = [
  { key: "OVERVIEW", label: "概览" },
  { key: "PLAN", label: "计划" },
  { key: "TRACE", label: "轨迹" },
  { key: "KNOWLEDGE", label: "知识" },
  { key: "DELIVERY", label: "交付" },
  { key: "COPILOT", label: "对话" },
];

const stageOrder: Array<{ key: OperatorAgentEventStage; label: string }> = [
  { key: "INTAKE", label: "理解" },
  { key: "TOOL", label: "工具" },
  { key: "KNOWLEDGE", label: "知识" },
  { key: "DELIVERY", label: "交付" },
  { key: "HUMAN_GATE", label: "人工" },
];

const traceFilters: Array<{ key: TraceFilter; label: string }> = [
  { key: "ALL", label: "全部" },
  { key: "TOOL", label: "工具" },
  { key: "KNOWLEDGE", label: "知识" },
  { key: "DELIVERY", label: "交付" },
  { key: "HUMAN_GATE", label: "闸门" },
];

function shortDigest(value: string): string {
  if (value.length <= 19) return value;
  return value.slice(0, 9) + "…" + value.slice(-7);
}

function formatDuration(value: number): string {
  if (value <= 0) return "—";
  if (value < 1000) return value.toFixed(value < 100 ? 1 : 0) + " ms";
  return (value / 1000).toFixed(2) + " s";
}

function eventIcon(event: OperatorAgentEvent) {
  if (event.stage === "TOOL") return <Wrench size={13} />;
  if (event.stage === "KNOWLEDGE") return <BookOpen size={13} />;
  if (event.stage === "HUMAN_GATE") return <LockKeyhole size={13} />;
  if (event.status === "COMPLETED") return <CheckCircle2 size={13} />;
  return <CircleDashed size={13} />;
}

function viewIcon(view: AgentPanelView) {
  if (view === "OVERVIEW") return <Activity size={12} />;
  if (view === "PLAN") return <ListChecks size={12} />;
  if (view === "TRACE") return <Wrench size={12} />;
  if (view === "KNOWLEDGE") return <BookOpen size={12} />;
  if (view === "DELIVERY") return <ClipboardCheck size={12} />;
  return <MessageSquare size={12} />;
}

function stageStatus(events: OperatorAgentEvent[]): OperatorAgentEvent["status"] {
  if (events.some((event) => event.status === "WAITING")) return "WAITING";
  if (events.some((event) => event.status === "WARNING")) return "WARNING";
  return "COMPLETED";
}

interface AgentActivityTraceProps {
  run: OperatorAnalysisRun;
  revealedEventCount: number;
  filter: TraceFilter;
  onFilter: (filter: TraceFilter) => void;
}

function AgentActivityTrace({
  run,
  revealedEventCount,
  filter,
  onFilter,
}: AgentActivityTraceProps) {
  const revealedEvents = run.events.slice(0, revealedEventCount);
  const visibleEvents = filter === "ALL"
    ? revealedEvents
    : revealedEvents.filter((event) => event.stage === filter);
  const replaying = revealedEventCount < run.events.length;

  return (
    <section className="agent-activity-section">
      <header>
        <span>ACTIVITY TRACE</span>
        <em>{visibleEvents.length}/{run.events.length} visible</em>
      </header>
      <div className="agent-trace-filters" role="toolbar" aria-label="筛选 Agent 活动轨迹">
        {traceFilters.map((item) => {
          const count = item.key === "ALL"
            ? run.events.length
            : run.events.filter((event) => event.stage === item.key).length;
          return (
            <button
              type="button"
              key={item.key}
              className={filter === item.key ? "is-active" : ""}
              aria-pressed={filter === item.key}
              onClick={() => onFilter(item.key)}
            >
              {item.label}<em>{count}</em>
            </button>
          );
        })}
      </div>
      <div className="agent-event-list" aria-live="polite">
        {visibleEvents.map((event) => (
          <details
            className={"agent-event is-" + event.status.toLowerCase()}
            key={run.analysis_run_id + "-" + event.sequence}
          >
            <summary>
              <span className="agent-event__rail">{eventIcon(event)}</span>
              <span className="agent-event__copy">
                <small>
                  {String(event.sequence).padStart(2, "0")} · {event.stage}
                  {event.tool_name ? " / " + event.tool_name : ""}
                </small>
                <strong>{event.summary}</strong>
              </span>
              <em>{event.duration_ms > 0 ? formatDuration(event.duration_ms) : event.status}</em>
              <ChevronDown className="agent-event__chevron" size={13} aria-hidden="true" />
            </summary>
            <div className="agent-event__receipt">
              <span>actor</span><code>{event.actor}</code>
              <span>action</span><code>{event.action}</code>
              <span>receipt</span>
              <code title={event.receipt_sha256}>{shortDigest(event.receipt_sha256)}</code>
              <span>evidence</span>
              <div>
                {event.evidence_refs.length > 0
                  ? event.evidence_refs.map((ref) => <code key={ref} title={ref}>{ref}</code>)
                  : <code>NO SEPARATE EVIDENCE REF</code>}
              </div>
            </div>
          </details>
        ))}
        {visibleEvents.length === 0 && !replaying ? (
          <div className="agent-view-empty">当前筛选下没有已落盘事件。</div>
        ) : null}
        {replaying ? (
          <div className="agent-trace-replay">
            <span /><span /><span />回放已落盘事件
          </div>
        ) : null}
      </div>
    </section>
  );
}

interface AgentKnowledgePanelProps {
  run: OperatorAnalysisRun;
}

function AgentKnowledgePanel({ run }: AgentKnowledgePanelProps) {
  return (
    <>
      <section className="agent-knowledge-card">
        <header>
          <span><BookOpen size={13} /> GOVERNED KNOWLEDGE</span>
          <em>{run.knowledge_hits.length} hit</em>
        </header>
        {run.knowledge_hits.length > 0 ? run.knowledge_hits.map((hit) => (
          <article key={hit.card_id}>
            <div>
              <strong>{hit.title}</strong>
              <span>{hit.permission_scope}</span>
            </div>
            <p>{hit.excerpt}</p>
            <dl>
              <div><dt>source</dt><dd>{hit.source}</dd></div>
              <div><dt>evidence</dt><dd title={hit.evidence_ref}>{hit.evidence_ref}</dd></div>
            </dl>
          </article>
        )) : (
          <div className="agent-view-empty">本次运行没有命中可授权读取的知识卡。</div>
        )}
      </section>

      <section className="agent-permission-ledger">
        <header><ShieldCheck size={13} /> KNOWLEDGE BOUNDARY</header>
        <dl>
          <div><dt>permission</dt><dd>local-read-only</dd></div>
          <div><dt>raw image egress</dt><dd>{run.raw_images_transmitted ? "DETECTED" : "0 · BLOCKED"}</dd></div>
          <div><dt>model calls</dt><dd>{run.model_call_count}</dd></div>
          <div><dt>production authority</dt><dd>{run.human_gate.production_authority}</dd></div>
        </dl>
        <p>只显示授权知识命中与证据引用；未连接的供应商、维修或设备数据库不会被补写成事实。</p>
      </section>
    </>
  );
}

interface OperatorAgentPanelProps {
  asset: OperatorImageAsset;
  run?: OperatorAnalysisRun;
  turns: OperatorCopilotTurn[];
  loading: boolean;
  analyzing: boolean;
  asking: boolean;
  error?: string;
  traceStale: boolean;
  revealedEventCount: number;
  selectedAnnotationLabel?: string;
  activeView: AgentPanelView;
  onActiveViewChange: (view: AgentPanelView) => void;
  onRun: () => void;
  onAsk: (question: string) => void;
  onCreateWorkOrder: () => void;
  onOpenCapa: () => void;
  onOpenEvidence: () => void;
  onOpenTaskWorkbench: () => void;
}

export function OperatorAgentPanel({
  asset,
  run,
  turns,
  loading,
  analyzing,
  asking,
  error,
  traceStale,
  revealedEventCount,
  selectedAnnotationLabel,
  activeView,
  onActiveViewChange,
  onRun,
  onAsk,
  onCreateWorkOrder,
  onOpenCapa,
  onOpenEvidence,
  onOpenTaskWorkbench,
}: OperatorAgentPanelProps) {
  const [traceFilter, setTraceFilter] = useState<TraceFilter>("ALL");
  const [question, setQuestion] = useState("");
  const [copyState, setCopyState] = useState<"IDLE" | "COPIED" | "FAILED">("IDLE");
  const conversationRef = useRef<HTMLDivElement>(null);
  const viewTabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const copyFeedbackTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const conversation = conversationRef.current;
    if (conversation) conversation.scrollTop = conversation.scrollHeight;
  }, [asking, turns.length]);

  useEffect(() => {
    setTraceFilter("ALL");
  }, [asset.asset_id, run?.analysis_run_id]);

  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== undefined) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
  }, []);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = question.trim();
    if (!normalized || asking || !run) return;
    onAsk(normalized);
    setQuestion("");
  };

  const changeViewFromKeyboard = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    let nextIndex: number | undefined;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % panelViews.length;
    if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + panelViews.length) % panelViews.length;
    }
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = panelViews.length - 1;
    if (nextIndex === undefined) return;
    const nextView = panelViews[nextIndex];
    if (!nextView) return;
    event.preventDefault();
    onActiveViewChange(nextView.key);
    viewTabRefs.current[nextIndex]?.focus();
  };

  const copyTraceReceipt = async () => {
    if (!run) return;
    if (copyFeedbackTimerRef.current !== undefined) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(run, null, 2));
      setCopyState("COPIED");
    } catch {
      setCopyState("FAILED");
    }
    copyFeedbackTimerRef.current = window.setTimeout(() => setCopyState("IDLE"), 2200);
  };

  if (loading) {
    return (
      <div className="agent-panel agent-panel--loading" aria-label="正在加载 Agent Trace">
        <div className="agent-skeleton is-wide" />
        <div className="agent-skeleton" />
        <div className="agent-skeleton" />
        <div className="agent-skeleton is-tall" />
        <span><LoaderCircle size={14} className="is-spinning" />读取本地 Trace 账本…</span>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="agent-panel agent-panel--empty">
        <span className="agent-empty-icon"><Bot size={26} /></span>
        <strong>为当前图片启动 Agent 取证</strong>
        <p>基于当前图片、标注 revision 与本地账本，运行可审计的受控工作流。</p>
        <div className="agent-empty-capabilities" aria-label="Agent 工作流能力">
          <span><ListChecks size={12} />任务理解</span>
          <span><Wrench size={12} />5 类工具</span>
          <span><LockKeyhole size={12} />人工闸门</span>
        </div>
        <button type="button" className="agent-run-button" onClick={onRun} disabled={analyzing}>
          {analyzing ? <LoaderCircle size={14} className="is-spinning" /> : <Play size={14} />}
          {analyzing ? "正在生成 Trace…" : "运行 Agent 取证"}
        </button>
        <small>LOCAL ONLY · 0 MODEL CALLS · RAW IMAGE EGRESS 0</small>
      </div>
    );
  }

  const toolEvents = run.events.filter((event) => event.stage === "TOOL");
  const toolDuration = toolEvents.reduce((total, event) => total + event.duration_ms, 0);
  const uniqueEvidenceRefs = new Set([
    ...run.events.flatMap((event) => event.evidence_refs),
    ...run.knowledge_hits.map((hit) => hit.evidence_ref),
    ...run.recommendation.evidence_refs,
  ]);
  const stageRecords = stageOrder.map((stage) => {
    const events = run.events.filter((event) => event.stage === stage.key);
    return {
      ...stage,
      events,
      status: stageStatus(events),
      duration: events.reduce((total, event) => total + event.duration_ms, 0),
      evidenceCount: new Set(events.flatMap((event) => event.evidence_refs)).size,
    };
  });
  const recommendationTone = run.recommendation.severity.toLowerCase();
  const bindingMatches = run.asset_sha256 === asset.source_sha256 && !traceStale;
  const canCreateWorkOrder = Boolean(selectedAnnotationLabel) && !traceStale;

  return (
    <div className="agent-panel">
      <section className="agent-run-summary agent-run-summary--expanded">
        <header>
          <span><Bot size={16} /></span>
          <div>
            <small>LOCAL AGENT · RECEIPT BOUND</small>
            <strong>取证完成 · 等待具名人工复核</strong>
          </div>
          <button type="button" onClick={onRun} disabled={analyzing} title="重新运行并生成新回执">
            {analyzing ? <LoaderCircle size={14} className="is-spinning" /> : <RotateCcw size={14} />}
          </button>
        </header>
        <div className="agent-run-statebar">
          <span className="is-complete"><CheckCircle2 size={11} />{run.execution_status}</span>
          <span className="is-waiting"><LockKeyhole size={11} />HUMAN REVIEW</span>
        </div>
        <div className="agent-run-facts">
          <span title={run.analysis_run_id}>run {shortDigest(run.analysis_run_id)}</span>
          <span>{run.tool_call_count} tools</span>
          <span>{run.events.length} receipts</span>
          <span>{run.model_call_count} model</span>
        </div>
        {traceStale ? (
          <div className="agent-stale-warning">
            <AlertTriangle size={13} />当前标注已变化；此 Trace 仍绑定 annotation rev {run.annotation_revision}。
          </div>
        ) : null}
      </section>

      <nav
        className="agent-panel-nav"
        role="tablist"
        aria-label="Agent 副驾驶工作视图"
        aria-orientation="horizontal"
      >
        {panelViews.map((view, index) => (
          <button
            type="button"
            key={view.key}
            ref={(node) => { viewTabRefs.current[index] = node; }}
            id={`operator-agent-tab-${view.key.toLowerCase()}`}
            role="tab"
            className={activeView === view.key ? "is-active" : ""}
            aria-selected={activeView === view.key}
            aria-controls={`operator-agent-panel-${view.key.toLowerCase()}`}
            tabIndex={activeView === view.key ? 0 : -1}
            onClick={() => onActiveViewChange(view.key)}
            onKeyDown={(event) => changeViewFromKeyboard(event, index)}
          >
            {viewIcon(view.key)}
            <span>{view.label}</span>
            {view.key === "TRACE" ? <em>{run.events.length}</em> : null}
            {view.key === "KNOWLEDGE" ? <em>{run.knowledge_hits.length}</em> : null}
            {view.key === "COPILOT" && turns.length > 0 ? <em>{turns.length}</em> : null}
          </button>
        ))}
      </nav>

      {error ? <div className="agent-inline-error"><AlertTriangle size={13} />{error}</div> : null}

      <div
        key={activeView}
        id={`operator-agent-panel-${activeView.toLowerCase()}`}
        className={"agent-panel__view is-" + activeView.toLowerCase()}
        role="tabpanel"
        aria-labelledby={`operator-agent-tab-${activeView.toLowerCase()}`}
        tabIndex={0}
      >
        {activeView === "OVERVIEW" ? (
          <>
            <section className="agent-binding-card">
              <header>
                <span><FileCheck2 size={13} /> CURRENT BINDING</span>
                <em className={bindingMatches ? "is-fresh" : "is-stale"}>
                  {bindingMatches ? "TRACE FRESH" : "TRACE STALE"}
                </em>
              </header>
              <div className="agent-binding-card__asset">
                <span>{asset.original_name.slice(0, 1).toUpperCase()}</span>
                <div>
                  <strong title={asset.original_name}>{asset.original_name}</strong>
                  <small>{asset.width} × {asset.height}px · {asset.format}</small>
                </div>
              </div>
              <dl>
                <div><dt>asset sha</dt><dd title={run.asset_sha256}>{shortDigest(run.asset_sha256)}</dd></div>
                <div><dt>annotation</dt><dd>rev {run.annotation_revision}</dd></div>
                <div><dt>backend</dt><dd>{run.backend}</dd></div>
                <div><dt>egress</dt><dd>{run.raw_images_transmitted ? "DETECTED" : "0 RAW"}</dd></div>
              </dl>
            </section>

            <section className="agent-mission-card">
              <header><ListChecks size={13} /> AGENT MISSION <em>RECORDED</em></header>
              <strong>{run.goal}</strong>
              <p>{run.intent}</p>
            </section>

            <section className="agent-stage-map">
              <header>
                <span>CONTROLLED LOOP</span>
                <em>evidence → action → human</em>
              </header>
              <div>
                {stageRecords.map((stage, index) => (
                  <article className={"is-" + stage.status.toLowerCase()} key={stage.key}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{stage.label}</strong>
                    <small>{stage.events.length} event</small>
                    {index < stageRecords.length - 1 ? <ArrowRight size={10} /> : null}
                  </article>
                ))}
              </div>
            </section>

            <section className="agent-overview-metrics" aria-label="本次 Agent 运行事实">
              <article><span>TOOLS</span><strong>{run.tool_call_count}</strong><small>{formatDuration(toolDuration)} total</small></article>
              <article><span>RECEIPTS</span><strong>{run.events.length}</strong><small>append-only trace</small></article>
              <article><span>EVIDENCE</span><strong>{uniqueEvidenceRefs.size}</strong><small>unique refs</small></article>
              <article><span>MODEL CALLS</span><strong>{run.model_call_count}</strong><small>deterministic path</small></article>
            </section>

            <div className="agent-trust-strip">
              <ShieldCheck size={13} />
              <span>证据与动作可审计；不显示模型私有思维链，不授予生产决策权。</span>
            </div>
          </>
        ) : null}

        {activeView === "PLAN" ? (
          <>
            <section className="agent-mission-card">
              <header><ListChecks size={13} /> TASK CONTRACT <em>{run.workflow_status}</em></header>
              <strong>{run.goal}</strong>
              <p>{run.intent}</p>
            </section>

            <section className="agent-plan-stage-list">
              <header><span>RECORDED EXECUTION PLAN</span><em>{stageRecords.length} stages</em></header>
              {stageRecords.map((stage, index) => {
                const lastEvent = stage.events.at(-1);
                return (
                  <article key={stage.key}>
                    <span className={"is-" + stage.status.toLowerCase()}>
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <header>
                        <strong>{stage.label} · {stage.key}</strong>
                        <em>{stage.status}</em>
                      </header>
                      <p>{lastEvent?.summary ?? "本阶段没有落盘事件。"}</p>
                      <small>
                        {stage.events.length} events · {stage.evidenceCount} evidence refs · {formatDuration(stage.duration)}
                      </small>
                    </div>
                  </article>
                );
              })}
            </section>

            <section className="agent-tool-roster">
              <header><Wrench size={13} /> DETERMINISTIC TOOL ROSTER <em>{toolEvents.length}</em></header>
              {toolEvents.map((event) => (
                <article key={event.sequence}>
                  <span className={"is-" + event.status.toLowerCase()}><Wrench size={11} /></span>
                  <div>
                    <strong>{event.tool_name ?? event.action}</strong>
                    <small>{event.status} · {formatDuration(event.duration_ms)}</small>
                  </div>
                  <code title={event.receipt_sha256}>{shortDigest(event.receipt_sha256)}</code>
                </article>
              ))}
            </section>

            <section className="agent-runtime-contract">
              <header><ShieldCheck size={13} /> RUNTIME CONTRACT</header>
              <dl>
                <div><dt>backend</dt><dd>{run.backend}</dd></div>
                <div><dt>connected</dt><dd>{run.backend_connected ? "true" : "false"}</dd></div>
                <div><dt>fallback</dt><dd>{run.fallback_used ? "used" : "not used"}</dd></div>
                <div><dt>model calls</dt><dd>{run.model_call_count}</dd></div>
                <div><dt>raw image sent</dt><dd>{run.raw_images_transmitted ? "true" : "false"}</dd></div>
                <div><dt>decision authority</dt><dd>{run.recommendation.decision_authority}</dd></div>
              </dl>
            </section>
          </>
        ) : null}

        {activeView === "TRACE" ? (
          <>
            <AgentActivityTrace
              run={run}
              revealedEventCount={revealedEventCount}
              filter={traceFilter}
              onFilter={setTraceFilter}
            />
            <footer className="agent-boundary agent-boundary--trace">
              <div className="agent-boundary__title">
                <strong>TRACE RECEIPT</strong>
                <button
                  type="button"
                  className={copyState === "FAILED" ? "is-error" : ""}
                  onClick={() => void copyTraceReceipt()}
                  aria-label="复制完整 Trace 回执"
                  title="复制本次已落盘的完整 Trace JSON"
                >
                  {copyState === "COPIED" ? <Check size={12} /> : <Copy size={12} />}
                  {copyState === "COPIED" ? "已复制" : copyState === "FAILED" ? "复制失败" : "复制回执"}
                </button>
              </div>
              <code title={run.document_sha256}>{shortDigest(run.document_sha256)}</code>
              <span>{asset.original_name} · SHA {shortDigest(asset.source_sha256)}</span>
              <span className="agent-copy-feedback" role="status" aria-live="polite">
                {copyState === "COPIED"
                  ? "完整 Trace JSON 已复制到剪贴板"
                  : copyState === "FAILED"
                    ? "浏览器拒绝剪贴板访问，请检查权限"
                    : "复制内容仅包含已交付运行事实，不包含私有思维链"}
              </span>
            </footer>
          </>
        ) : null}

        {activeView === "KNOWLEDGE" ? <AgentKnowledgePanel run={run} /> : null}

        {activeView === "DELIVERY" ? (
          <>
            <section className={"agent-recommendation is-" + recommendationTone}>
              <header>
                <span>AGENT 建议 · {run.recommendation.severity}</span>
                <code>{run.recommendation.code}</code>
              </header>
              <strong>{run.recommendation.title}</strong>
              <p>{run.recommendation.summary}</p>
              <div><ShieldCheck size={13} />{run.recommendation.next_action}</div>
              <details className="agent-recommendation-evidence">
                <summary>查看 {run.recommendation.evidence_refs.length} 条建议依据</summary>
                {run.recommendation.evidence_refs.map((ref) => <code key={ref}>{ref}</code>)}
              </details>
              <small>decision_authority = {run.recommendation.decision_authority}</small>
            </section>

            <section className="agent-action-dock">
              <header>
                <span><ClipboardCheck size={13} /> NEXT CONTROLLED ACTION</span>
                <em>HUMAN REQUIRED</em>
              </header>
              <button
                type="button"
                className="is-primary"
                disabled={!canCreateWorkOrder}
                onClick={onCreateWorkOrder}
              >
                <ClipboardCheck size={14} />
                <span>
                  <strong>复核并创建本地工单</strong>
                  <small>
                    {traceStale
                      ? "标注已变化，请先重新运行 Agent"
                      : selectedAnnotationLabel
                        ? "当前缺陷：" + selectedAnnotationLabel
                        : "先在画布中选中一个缺陷框"}
                  </small>
                </span>
                <ArrowRight size={13} />
              </button>
              <div>
                <button type="button" onClick={onOpenCapa}><ExternalLink size={12} />CAPA 队列</button>
                <button type="button" onClick={onOpenEvidence}><FileCheck2 size={12} />证据库</button>
                <button type="button" onClick={onOpenTaskWorkbench}><Activity size={12} />工作总览</button>
              </div>
            </section>

            <section className="agent-human-gate">
              <span><LockKeyhole size={15} /></span>
              <div><strong>HUMAN-IN-THE-LOOP</strong><p>{run.human_gate.required_action}</p></div>
              <button type="button" onClick={onOpenCapa}><ExternalLink size={13} />CAPA</button>
            </section>

            <footer className="agent-boundary">
              <strong>DELIVERY BOUNDARY</strong>
              <code>{run.human_gate.status} · authority {run.human_gate.production_authority}</code>
              <p>{run.boundary_notice}</p>
              <span>receipt {shortDigest(run.document_sha256)}</span>
            </footer>
          </>
        ) : null}

        {activeView === "COPILOT" ? (
          <>
            <section className="agent-copilot">
              <header>
                <span><MessageSquare size={13} /> EVIDENCE COPILOT</span>
                <em>{turns.length} TURNS · LOCAL GROUNDED</em>
              </header>
              <div className="agent-copilot-context">
                <span title={asset.original_name}>{asset.original_name}</span>
                <code>rev {run.annotation_revision}</code>
                <strong className={traceStale ? "is-stale" : "is-fresh"}>
                  {traceStale ? "STALE TRACE" : "BOUND TRACE"}
                </strong>
              </div>
              <div className="agent-conversation" ref={conversationRef}>
                <div className="agent-message is-agent">
                  <span><Bot size={12} /></span>
                  <div>
                    <p>我可以基于本次 Trace 查询重复、质量指标、标注 revision、工单与安全边界。</p>
                    <small>不连接供应商/维修数据库，不会补写缺失事实。</small>
                  </div>
                </div>
                {turns.map((turn) => (
                  <div className="agent-turn" key={turn.turn_id}>
                    <div className="agent-message is-user"><div><p>{turn.question}</p></div></div>
                    <div className="agent-message is-agent">
                      <span><Bot size={12} /></span>
                      <div>
                        <p>{turn.answer}</p>
                        <details>
                          <summary>查看 {turn.evidence_refs.length} 条证据与回执</summary>
                          {turn.evidence_refs.map((ref) => <code key={ref}>{ref}</code>)}
                          <code>turn {shortDigest(turn.document_sha256)}</code>
                        </details>
                      </div>
                    </div>
                  </div>
                ))}
                {asking ? (
                  <div className="agent-message is-agent is-thinking">
                    <span><Bot size={12} /></span><div><span /><span /><span /></div>
                  </div>
                ) : null}
              </div>
              <div className="agent-quick-questions">
                {quickQuestions.map((item) => (
                  <button type="button" key={item} disabled={asking} onClick={() => onAsk(item)}>
                    {item}
                  </button>
                ))}
              </div>
              <form className="agent-question-form" onSubmit={submit}>
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="只问当前 Trace 中可验证的事实…"
                  maxLength={600}
                />
                <button type="submit" disabled={!question.trim() || asking} aria-label="发送问题">
                  {asking ? <LoaderCircle size={14} className="is-spinning" /> : <Send size={14} />}
                </button>
              </form>
            </section>
            <div className="agent-trust-strip">
              <ShieldCheck size={13} />
              <span>展示的是证据化动作与回答依据，不是模型私有思维链。</span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
