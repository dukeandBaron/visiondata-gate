import {
  ArrowRight,
  Bot,
  Braces,
  Cable,
  CheckCircle2,
  Database,
  FileCheck2,
  HardDrive,
  KeyRound,
  Layers3,
  Link2,
  LoaderCircle,
  PackageOpen,
  PlugZap,
  RadioTower,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type {
  AgentRuntimeCapabilities,
  HostedAgentTeamsReceipt,
  LocalTaskSource,
  SourceAuthorizationEvent,
} from "../agentDomain";
import { ClaimBoundary, EvidenceSourceBadge, StatusBadge } from "../components/ui";
import {
  authorizeLocalTaskSource,
  getAgentRuntimeCapabilities,
  getHostedAgentTeamsHealthStatus,
  listLocalTaskSources,
  listSourceAuthorizationEvents,
  probeHostedAgentTeams,
  revokeLocalTaskSource,
  type HostedAgentTeamsHealthStatus,
} from "../data/api";
import { integrationCatalog } from "../data/integrationCatalog";
import type { IntegrationRecord } from "../domain";
import { useProduct } from "../ProductContext";

const categories = ["ALL", "ANNOTATION", "DATA", "API", "FORMAT", "AGENT", "MODEL"] as const;
type HubMode = "WORKFLOWS" | "SKILLS" | "CONNECTORS";

interface WorkflowMember {
  icon: LucideIcon;
  title: string;
  detail: string;
}

interface WorkflowGroup {
  id: "DATA" | "API" | "AGENT" | "GOVERNANCE";
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tone: "cyan" | "violet" | "coral" | "lime";
  targetId?: string;
  route?: string;
  members: WorkflowMember[];
}

const workflowGroups: WorkflowGroup[] = [
  {
    id: "DATA",
    eyebrow: "DATA INTAKE",
    title: "数据接入工作流",
    description: "从授权目录进入可追溯数据上下文。",
    icon: Database,
    tone: "cyan",
    targetId: "local-source",
    members: [
      { icon: HardDrive, title: "授权来源", detail: "只读范围与权利回执" },
      { icon: PackageOpen, title: "格式适配", detail: "manifest / observation" },
      { icon: CheckCircle2, title: "完整性收据", detail: "SHA 与事件链" },
    ],
  },
  {
    id: "API",
    eyebrow: "SERVICE PLANE",
    title: "API 服务协同",
    description: "把项目、任务、证据和工单接入同一服务面。",
    icon: PlugZap,
    tone: "violet",
    targetId: "rest-api",
    members: [
      { icon: Braces, title: "REST 合同", detail: "本地 /v1 API" },
      { icon: Layers3, title: "任务与证据", detail: "Task / Finding / Receipt" },
      { icon: Link2, title: "CAPA 与血缘", detail: "受控动作与演进" },
    ],
  },
  {
    id: "AGENT",
    eyebrow: "AGENT RUNTIME",
    title: "Agent 运行专家组",
    description: "模型只负责理解与协同，工具回执负责确定性。",
    icon: Bot,
    tone: "coral",
    targetId: "agentteams",
    members: [
      { icon: Workflow, title: "AgentTeams", detail: "托管传输合同" },
      { icon: Wrench, title: "确定性工具", detail: "ToolTrace 与原子回执" },
      { icon: KeyRound, title: "模型 Profile", detail: "服务端凭证边界" },
    ],
  },
  {
    id: "GOVERNANCE",
    eyebrow: "GOVERNED DELIVERY",
    title: "治理与交付闭环",
    description: "所有高责任动作在人工闸门前停止。",
    icon: ShieldCheck,
    tone: "lime",
    route: "/governance",
    members: [
      { icon: FileCheck2, title: "授权账本", detail: "append-only events" },
      { icon: RefreshCw, title: "影子评测", detail: "同合同复验" },
      { icon: ShieldCheck, title: "发布门禁", detail: "fail closed" },
    ],
  },
];

function stateLabel(state: IntegrationRecord["state"]): string {
  return state.replaceAll("_", " ");
}

function hubStateLabel(state: IntegrationRecord["state"]): string {
  const labels: Record<string, string> = {
    LOCAL_CONTRACT_VERIFIED: "本地可用",
    CONTRACT_READY_NOT_CONNECTED: "合同就绪",
    LOCAL_API_AVAILABLE: "服务可用",
    ADAPTER_SDK_AVAILABLE: "可扩展",
    MAPPED_NOT_CONNECTED: "待连接",
    NOT_TESTED: "未测试",
  };
  return labels[state] ?? stateLabel(state);
}

function shortDigest(value: string | null | undefined): string {
  if (!value) return "—";
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function iconForCategory(category: IntegrationRecord["category"]): LucideIcon {
  if (category === "API") return PlugZap;
  if (category === "DATA") return Database;
  if (category === "FORMAT") return PackageOpen;
  if (category === "AGENT" || category === "MODEL") return Bot;
  return Cable;
}

export function IntegrationsPage() {
  const navigate = useNavigate();
  const { activeWorkspace, connection } = useProduct();
  const [hubMode, setHubMode] = useState<HubMode>("WORKFLOWS");
  const [category, setCategory] = useState<(typeof categories)[number]>("ALL");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(integrationCatalog[0]?.id ?? "");
  const [sources, setSources] = useState<LocalTaskSource[]>([]);
  const [runtimeCapabilities, setRuntimeCapabilities] = useState<AgentRuntimeCapabilities>();
  const [hostedHealthStatus, setHostedHealthStatus] = useState<HostedAgentTeamsHealthStatus>();
  const [hostedProbeReceipt, setHostedProbeReceipt] = useState<HostedAgentTeamsReceipt>();
  const [hostedProbeLoading, setHostedProbeLoading] = useState(false);
  const [hostedProbeError, setHostedProbeError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [refreshToken, setRefreshToken] = useState(0);
  const [sourceSubmitting, setSourceSubmitting] = useState(false);
  const [sourceFeedback, setSourceFeedback] = useState<string>();
  const [sourceEvents, setSourceEvents] = useState<Record<string, SourceAuthorizationEvent[]>>({});
  const [revokingSourceId, setRevokingSourceId] = useState("");
  const [revokeReason, setRevokeReason] = useState("");
  const [revoking, setRevoking] = useState(false);
  const [sourceForm, setSourceForm] = useState({
    displayName: "",
    rootPath: "",
    sourceArchiveSha256: "",
    purpose: "",
    rightsBasis: "",
    attested: false,
  });
  const hostedProbeGenerationRef = useRef(0);

  useEffect(() => {
    hostedProbeGenerationRef.current += 1;
    setHostedProbeReceipt(undefined);
    setHostedProbeError(undefined);
    setHostedProbeLoading(false);
  }, [activeWorkspace?.workspace_id]);

  useEffect(() => {
    let active = true;
    const workspaceId = activeWorkspace?.workspace_id;
    setSources([]);
    setSourceEvents({});
    setRuntimeCapabilities(undefined);
    setHostedHealthStatus(undefined);
    setError(undefined);
    setLoading(false);
    if (!workspaceId || connection.api !== "CONNECTED") return () => {
      active = false;
    };
    setLoading(true);
    void Promise.allSettled([
      listLocalTaskSources(workspaceId),
      getAgentRuntimeCapabilities(),
      getHostedAgentTeamsHealthStatus(),
    ]).then(([sourceResult, capabilityResult, hostedHealthResult]) => {
      if (!active) return;
      if (sourceResult.status === "fulfilled") {
        setSources(sourceResult.value);
        void Promise.all(
          sourceResult.value.map(async (source) => [
            source.source_id,
            await listSourceAuthorizationEvents(source.source_id),
          ] as const),
        ).then((entries) => {
          if (active) setSourceEvents(Object.fromEntries(entries));
        }).catch((caught) => {
          if (active) setError((current) => current ?? (caught instanceof Error ? caught.message : "来源事件账本不可用"));
        });
      } else {
        setError(sourceResult.reason instanceof Error ? sourceResult.reason.message : "数据源接口不可用");
      }
      if (capabilityResult.status === "fulfilled") setRuntimeCapabilities(capabilityResult.value);
      else setError((current) => current ?? (capabilityResult.reason instanceof Error ? capabilityResult.reason.message : "Runtime 能力接口不可用"));
      if (hostedHealthResult.status === "fulfilled") setHostedHealthStatus(hostedHealthResult.value);
      else setError((current) => current ?? (hostedHealthResult.reason instanceof Error ? hostedHealthResult.reason.message : "Hosted AgentTeams 本地健康状态不可用"));
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [activeWorkspace?.workspace_id, connection.api, refreshToken]);

  const resolvedIntegrations = useMemo<IntegrationRecord[]>(() => integrationCatalog.map((item) => {
    if (item.id === "rest-api") {
      return connection.api === "CONNECTED"
        ? item
        : { ...item, state: "MAPPED_NOT_CONNECTED", tone: "danger", source: "NOT_CONNECTED", boundary: "当前浏览器未连接本地 API；所有写操作保持不可用。" };
    }
    if (item.id === "local-source") {
      const activeCount = sources.filter((source) => source.status === "active").length;
      return {
        ...item,
        capability: `${item.capability} · 当前工作空间 active=${activeCount}`,
        tone: activeCount ? "success" : "warning",
      };
    }
    if (item.id === "external-models" && runtimeCapabilities) {
      const available = runtimeCapabilities.model_profiles.filter((profile) => profile.availability === "AVAILABLE").length;
      return { ...item, capability: `${item.capability} · server profiles available=${available}/${runtimeCapabilities.model_profiles.length}` };
    }
    if (item.id === "agentteams") {
      if (hostedProbeReceipt) {
        return {
          ...item,
          tone: hostedProbeReceipt.status === "PASS" ? "success" : hostedProbeReceipt.status === "FAIL" ? "danger" : "warning",
          source: "LIVE_API",
          capability: `${item.capability} · ${hostedProbeReceipt.operation_status}`,
          boundary: hostedProbeReceipt.boundary,
        };
      }
      if (hostedHealthStatus === "NOT_CONFIGURED") {
        return {
          ...item,
          tone: "locked",
          capability: `${item.capability} · NOT_CONFIGURED`,
          boundary: "服务端未配置 Hosted AgentTeams；页面不会发起远程网络请求。",
        };
      }
      if (hostedHealthStatus === "CONFIGURED_NOT_PROBED") {
        return {
          ...item,
          tone: "warning",
          capability: `${item.capability} · CONFIGURED_NOT_PROBED`,
          boundary: "仅确认服务端配置存在；尚未执行用户触发的远程只读探测。",
        };
      }
    }
    return item;
  }), [connection.api, hostedHealthStatus, hostedProbeReceipt, runtimeCapabilities, sources]);

  const modeCategories = useMemo(() => {
    if (hubMode === "SKILLS") return ["ALL", "ANNOTATION", "DATA", "FORMAT", "AGENT"] as const;
    if (hubMode === "CONNECTORS") return ["ALL", "ANNOTATION", "API", "AGENT", "MODEL"] as const;
    return categories;
  }, [hubMode]);

  const visible = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return resolvedIntegrations.filter((item) => {
      const modeMatch = hubMode === "WORKFLOWS"
        || (hubMode === "SKILLS" && ["ANNOTATION", "DATA", "FORMAT", "AGENT"].includes(item.category))
        || (hubMode === "CONNECTORS" && ["ANNOTATION", "API", "AGENT", "MODEL"].includes(item.category));
      const categoryMatch = category === "ALL" || item.category === category;
      const searchMatch = !normalizedQuery || [item.name, item.category, item.protocol, item.capability]
        .some((value) => value.toLowerCase().includes(normalizedQuery));
      return modeMatch && categoryMatch && searchMatch;
    });
  }, [category, hubMode, query, resolvedIntegrations]);

  const selected = resolvedIntegrations.find((item) => item.id === selectedId) ?? resolvedIntegrations[0];
  const activeSourceCount = sources.filter((source) => source.status === "active").length;
  const availableModelCount = runtimeCapabilities?.model_profiles.filter((profile) => profile.availability === "AVAILABLE").length ?? 0;
  const hostedObservedStatus = hostedProbeReceipt?.operation_status ?? hostedHealthStatus ?? "STATUS_UNAVAILABLE";

  const changeHubMode = (mode: HubMode) => {
    setHubMode(mode);
    setCategory("ALL");
  };

  const openIntegration = (id: string, scroll = true) => {
    setSelectedId(id);
    if (scroll) window.setTimeout(() => document.getElementById("integration-hub-inspector")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };

  const openWorkflow = (group: WorkflowGroup) => {
    if (group.route) {
      navigate(group.route);
      return;
    }
    if (group.targetId) openIntegration(group.targetId);
  };

  const workflowStatus = (id: WorkflowGroup["id"]): string => {
    if (id === "DATA") return activeSourceCount ? `${activeSourceCount} ACTIVE` : "待授权";
    if (id === "API") return connection.api;
    if (id === "AGENT") return hostedObservedStatus;
    return "HUMAN GATE";
  };

  const authorizeSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const workspaceId = activeWorkspace?.workspace_id;
    if (!workspaceId || sourceSubmitting || !sourceForm.attested) return;
    setSourceSubmitting(true);
    setError(undefined);
    setSourceFeedback(undefined);
    try {
      if (!/^[0-9a-f]{64}$/.test(sourceForm.sourceArchiveSha256)) {
        throw new Error("Source Archive 必须是 64 位小写 SHA-256");
      }
      const created = await authorizeLocalTaskSource({
        workspaceId,
        displayName: sourceForm.displayName,
        rootPath: sourceForm.rootPath,
        sourceArchiveSha256: sourceForm.sourceArchiveSha256,
        purpose: sourceForm.purpose,
        rightsBasis: sourceForm.rightsBasis,
      });
      setSources((current) => [created, ...current.filter((item) => item.source_id !== created.source_id)]);
      setSourceFeedback(`只读来源 ${created.source_id} 已登记；服务端响应未向页面返回原始路径。`);
      setSourceForm((current) => ({ ...current, displayName: "", rootPath: "", sourceArchiveSha256: "", purpose: "", rightsBasis: "", attested: false }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "本地来源登记失败");
    } finally {
      setSourceSubmitting(false);
    }
  };

  const revokeSource = async (source: LocalTaskSource) => {
    if (revoking || revokeReason.trim().length < 8) return;
    setRevoking(true);
    setError(undefined);
    setSourceFeedback(undefined);
    try {
      const event = await revokeLocalTaskSource({
        sourceId: source.source_id,
        reason: revokeReason.trim(),
        expectedLatestEventSha256: source.latest_authorization_event_sha256,
      });
      setSources((current) => current.map((item) => item.source_id === source.source_id
        ? {
            ...item,
            status: "revoked",
            authorization_event_count: item.authorization_event_count + 1,
            latest_authorization_event_type: "REVOKED",
            latest_authorization_event_sha256: event.event_sha256,
          }
        : item));
      setSourceEvents((current) => ({
        ...current,
        [source.source_id]: [...(current[source.source_id] ?? []), event],
      }));
      setSourceFeedback(`来源 ${source.source_id} 已撤销；${event.fail_closed_task_ids.length} 个未开始任务被失败关闭。源字节仍由操作者管理，系统未删除文件。`);
      setRevokingSourceId("");
      setRevokeReason("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "来源撤销失败");
    } finally {
      setRevoking(false);
    }
  };

  const probeHostedTransport = async () => {
    const workspaceId = activeWorkspace?.workspace_id;
    if (
      !workspaceId ||
      connection.api !== "CONNECTED" ||
      hostedHealthStatus !== "CONFIGURED_NOT_PROBED" ||
      hostedProbeLoading
    ) return;
    const generation = ++hostedProbeGenerationRef.current;
    setHostedProbeLoading(true);
    setHostedProbeReceipt(undefined);
    setHostedProbeError(undefined);
    try {
      const receipt = await probeHostedAgentTeams(workspaceId);
      if (generation !== hostedProbeGenerationRef.current) return;
      setHostedProbeReceipt(receipt);
    } catch (caught) {
      if (generation !== hostedProbeGenerationRef.current) return;
      setHostedProbeError(caught instanceof Error ? caught.message : "Hosted AgentTeams 只读探测失败关闭");
    } finally {
      if (generation === hostedProbeGenerationRef.current) setHostedProbeLoading(false);
    }
  };

  return (
    <div className="integration-hub-page">
      <section className="integration-hub-toolbar">
        <nav aria-label="集成中心视图">
          <button type="button" className={hubMode === "WORKFLOWS" ? "is-active" : ""} onClick={() => changeHubMode("WORKFLOWS")}><Sparkles size={16} /> 工作流</button>
          <button type="button" className={hubMode === "SKILLS" ? "is-active" : ""} onClick={() => changeHubMode("SKILLS")}><Wrench size={16} /> 适配技能</button>
          <button type="button" className={hubMode === "CONNECTORS" ? "is-active" : ""} onClick={() => changeHubMode("CONNECTORS")}><Link2 size={16} /> 连接器</button>
        </nav>
        <label><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 API、数据、格式或运行时" /></label>
        <button type="button" className="integration-hub-toolbar__sources" onClick={() => openIntegration("local-source")}><HardDrive size={15} /> 我的来源 <span>{activeSourceCount}</span></button>
        <button type="button" className="integration-hub-toolbar__refresh" onClick={() => setRefreshToken((value) => value + 1)} disabled={loading || connection.api !== "CONNECTED"} title="刷新真实状态">{loading ? <LoaderCircle className="is-spinning" size={15} /> : <RefreshCw size={15} />}</button>
      </section>

      <header className="integration-hub-heading">
        <div><span>INTEGRATION SKILL HUB</span><h1>{hubMode === "WORKFLOWS" ? "精选工作流程" : hubMode === "SKILLS" ? "适配技能目录" : "连接器目录"}</h1><p>{hubMode === "WORKFLOWS" ? "按工业数据真正流转的顺序组织能力，不再让协议名和状态字段主导页面。" : hubMode === "SKILLS" ? "查看可在本机复用、扩展或组合的适配能力。" : "查看外部系统与运行时的真实连接边界。"}</p></div>
        <div className="integration-hub-heading__status"><span><i className={`runtime-dot runtime-dot--${connection.api.toLowerCase()}`} /> API {connection.api}</span><span>{activeSourceCount} AUTHORIZED SOURCE</span><span>EXTERNAL VERIFIED · 0</span></div>
      </header>

      {error ? <ClaimBoundary title="部分接口不可用" tone="warning">{error}</ClaimBoundary> : null}

      {hubMode === "WORKFLOWS" ? (
        <section className="integration-workflow-grid" aria-label="精选集成工作流程">
          {workflowGroups.map((group) => (
            <article className={`integration-workflow-card is-${group.tone}`} key={group.id}>
              <div className="integration-workflow-card__backdrop"><span>✦</span><i /><i /><i /></div>
              <header><span className="integration-workflow-card__icon"><group.icon size={19} /></span><div><small>{group.eyebrow}</small><h2>{group.title}</h2></div><em>{workflowStatus(group.id)}</em></header>
              <p>{group.description}</p>
              <div className="integration-workflow-members">
                {group.members.map((member) => (
                  <div key={member.title}><span><member.icon size={15} /></span><div><strong>{member.title}</strong><small>{member.detail}</small></div></div>
                ))}
              </div>
              <button type="button" onClick={() => openWorkflow(group)}>进入流程 <ArrowRight size={15} /></button>
            </article>
          ))}
        </section>
      ) : null}

      <section className="integration-hub-catalog">
        <header>
          <div><span>{hubMode === "WORKFLOWS" ? "INTEGRATION UNITS" : hubMode}</span><h2>{hubMode === "WORKFLOWS" ? "集成单元" : hubMode === "SKILLS" ? "适配技能" : "连接器"}</h2></div>
          <div><StatusBadge tone="info" compact>{visible.length} ITEMS</StatusBadge><span>状态来自本机合同与实时探测</span></div>
        </header>
        <div className="integration-hub-filters" aria-label="集成类别筛选">
          {modeCategories.map((value) => <button type="button" key={value} className={category === value ? "is-active" : ""} onClick={() => setCategory(value)}>{value === "ALL" ? "全部" : value}</button>)}
        </div>

        {visible.length ? (
          <div className="integration-hub-grid">
            {visible.map((integration, index) => {
              const Icon = iconForCategory(integration.category);
              return (
                <article key={integration.id} className={`integration-hub-card${selected?.id === integration.id ? " is-selected" : ""}`}>
                  <span className="integration-hub-card__number">{String(index + 1).padStart(2, "0")}</span>
                  <header><span className={`integration-hub-card__icon is-${integration.tone}`}><Icon size={19} /></span><div><small>{integration.category}</small><h3>{integration.name}</h3></div><i className={`is-${integration.tone}`} /></header>
                  <p>{integration.capability}</p>
                  <div className="integration-hub-card__tags"><span>{integration.protocol.split(" · ")[0]}</span><span>{integration.id === "agentteams" ? hostedObservedStatus : hubStateLabel(integration.state)}</span></div>
                  <footer><EvidenceSourceBadge source={integration.source} /><button type="button" onClick={() => openIntegration(integration.id)}>查看合同与状态 <ArrowRight size={14} /></button></footer>
                </article>
              );
            })}
          </div>
        ) : <div className="integration-hub-empty"><Search size={22} /><strong>没有匹配的能力</strong><p>调整搜索词或分类筛选。</p></div>}
      </section>

      {selected ? (
        <section className="integration-hub-inspector" id="integration-hub-inspector">
          <header>
            <span className={`integration-hub-inspector__icon is-${selected.tone}`}>{(() => { const Icon = iconForCategory(selected.category); return <Icon size={23} />; })()}</span>
            <div><small>SELECTED CONTRACT · {selected.category}</small><h2>{selected.name}</h2><p>合同能力与当前连接观察保持分离。</p></div>
            {loading ? <LoaderCircle className="is-spinning" size={17} /> : <StatusBadge tone={selected.tone}>{selected.id === "agentteams" ? hostedObservedStatus : stateLabel(selected.state)}</StatusBadge>}
          </header>
          <div className="integration-hub-contract-grid">
            <div><span>PROTOCOL</span><strong>{selected.protocol}</strong></div>
            <div><span>CAPABILITY</span><strong>{selected.capability}</strong></div>
            <div><span>BOUNDARY</span><strong>{selected.boundary}</strong></div>
            <div><span>OBSERVATION</span><strong>{selected.id === "local-source" ? `${sources.length} total / ${activeSourceCount} active` : selected.id === "external-models" && runtimeCapabilities ? `${availableModelCount}/${runtimeCapabilities.model_profiles.length} profiles available` : selected.id === "agentteams" ? hostedObservedStatus : `API ${connection.api}`}</strong></div>
          </div>

          {selected.id === "local-source" ? (
            <div className="integration-hub-source-area">
              <details className="integration-hub-config">
                <summary><span><HardDrive size={17} /></span><div><strong>登记新的只读来源</strong><small>展开后填写路径、用途、权利依据与 Source Archive SHA-256。</small></div><ArrowRight size={14} /></summary>
                <form className="integration-source-form" onSubmit={(event) => void authorizeSource(event)}>
                  <header><strong>登记服务端本地只读目录</strong><span>路径仅提交给本机 API；公开回执只保留路径摘要。</span></header>
                  <div><label><span>显示名称</span><input required minLength={2} value={sourceForm.displayName} onChange={(event) => setSourceForm((current) => ({ ...current, displayName: event.target.value }))} /></label><label><span>服务端绝对目录</span><input required value={sourceForm.rootPath} onChange={(event) => setSourceForm((current) => ({ ...current, rootPath: event.target.value }))} placeholder="例如：受控数据根目录下的 omni-release" /></label></div>
                  <label><span>Source Archive SHA-256</span><input required pattern="[0-9a-f]{64}" spellCheck={false} value={sourceForm.sourceArchiveSha256} onChange={(event) => setSourceForm((current) => ({ ...current, sourceArchiveSha256: event.target.value.trim() }))} /></label>
                  <div><label><span>使用目的</span><textarea required minLength={8} value={sourceForm.purpose} onChange={(event) => setSourceForm((current) => ({ ...current, purpose: event.target.value }))} /></label><label><span>权利依据</span><textarea required minLength={8} value={sourceForm.rightsBasis} onChange={(event) => setSourceForm((current) => ({ ...current, rightsBasis: event.target.value }))} /></label></div>
                  <label className="integration-source-attestation"><input type="checkbox" checked={sourceForm.attested} onChange={(event) => setSourceForm((current) => ({ ...current, attested: event.target.checked }))} /><span>我确认有权将该目录用于本地只读治理；不允许原图再分发。</span></label>
                  {sourceFeedback ? <p className="integration-source-feedback">{sourceFeedback}</p> : null}
                  <button type="submit" disabled={!sourceForm.attested || sourceSubmitting || connection.api !== "CONNECTED" || !activeWorkspace}>{sourceSubmitting ? <LoaderCircle className="is-spinning" size={13} /> : <CheckCircle2 size={13} />}{sourceSubmitting ? "正在画像并登记…" : "登记只读来源"}</button>
                </form>
              </details>

              <details className="integration-hub-config">
                <summary><span><FileCheck2 size={17} /></span><div><strong>来源授权与事件账本</strong><small>{sources.length ? `${sources.length} 个来源回执，${activeSourceCount} 个保持 active。` : "当前工作空间尚无来源回执。"}</small></div><ArrowRight size={14} /></summary>
                <section className="integration-source-ledger">
                  {sources.length === 0 ? <p>当前工作空间尚无来源回执。</p> : sources.map((source) => (
                    <article key={source.source_id}>
                      <div className="integration-source-ledger__summary"><div><small>{source.adapter_kind}</small><strong>{source.display_name}</strong><code>{source.source_id} · {shortDigest(source.source_archive_sha256)}</code></div><StatusBadge tone={source.status === "active" ? "success" : source.status === "revoked" ? "danger" : "warning"} compact>{source.status.toUpperCase()}</StatusBadge></div>
                      <dl><div><dt>events</dt><dd>{source.authorization_event_count}</dd></div><div><dt>latest event</dt><dd>{shortDigest(source.latest_authorization_event_sha256)}</dd></div><div><dt>assets copied</dt><dd>{String(source.source_assets_copied_into_product)}</dd></div><div><dt>created</dt><dd>{new Date(source.created_at).toLocaleString()}</dd></div></dl>
                      <details><summary>查看 append-only 事件历史</summary>{(sourceEvents[source.source_id] ?? []).map((event) => <p key={event.event_id}><strong>#{event.sequence} {event.event_type}</strong><span>{event.reason}</span><code>{shortDigest(event.event_sha256)} · {event.actor_id}</code></p>)}</details>
                      {source.status === "active" ? revokingSourceId === source.source_id ? <div className="integration-source-revoke"><textarea value={revokeReason} minLength={8} maxLength={1000} onChange={(event) => setRevokeReason(event.target.value)} placeholder="填写至少 8 个字符的永久撤销原因" autoFocus /><div><button type="button" onClick={() => { setRevokingSourceId(""); setRevokeReason(""); }} disabled={revoking}>保留授权</button><button type="button" className="is-danger" onClick={() => void revokeSource(source)} disabled={revoking || revokeReason.trim().length < 8}>{revoking ? "正在撤销…" : "永久撤销此授权"}</button></div></div> : <button type="button" className="integration-source-revoke-trigger" onClick={() => { setRevokingSourceId(source.source_id); setRevokeReason(""); }}>撤销来源授权</button> : null}
                    </article>
                  ))}
                </section>
              </details>
            </div>
          ) : null}

          {selected.id === "agentteams" ? (
            <section className="hosted-transport-console" aria-label="Hosted AgentTeams 受控传输">
              <header>
                <span><RadioTower size={18} /></span>
                <div>
                  <small>HOSTED TRANSPORT CUSTODY</small>
                  <strong>先看本地配置，再由操作者触发只读探测</strong>
                  <p>打开页面不会连接 Hosted AgentTeams，也不会提交 Task。</p>
                </div>
                <StatusBadge
                  tone={hostedProbeReceipt?.status === "PASS" ? "success" : hostedHealthStatus === "NOT_CONFIGURED" ? "locked" : "warning"}
                  compact
                >
                  {hostedObservedStatus}
                </StatusBadge>
              </header>

              <div className="hosted-transport-rail" aria-label="Hosted AgentTeams 操作边界">
                <article className="is-observed"><span>01</span><div><strong>本地健康读取</strong><small>{hostedHealthStatus ?? "STATUS_UNAVAILABLE"}</small></div></article>
                <i />
                <article className={hostedProbeReceipt ? "is-observed" : ""}><span>02</span><div><strong>远程只读探测</strong><small>{hostedProbeReceipt ? hostedProbeReceipt.operation_status : "仅在点击后发生"}</small></div></article>
                <i />
                <article><span>03</span><div><strong>Task 提交</strong><small>仅在任务工作台具名批准</small></div></article>
              </div>

              <div className="hosted-transport-action">
                <div>
                  <strong>{hostedHealthStatus === "NOT_CONFIGURED" ? "Hosted transport 未配置" : "执行新的远程只读证据尝试"}</strong>
                  <p>{hostedHealthStatus === "NOT_CONFIGURED" ? "服务端已失败关闭；没有远程网络请求可执行。" : "只读取 controller / team / worker 状态；不会注册项目或委派工作。"}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void probeHostedTransport()}
                  disabled={hostedHealthStatus !== "CONFIGURED_NOT_PROBED" || hostedProbeLoading || !activeWorkspace || connection.api !== "CONNECTED"}
                >
                  {hostedProbeLoading ? <LoaderCircle className="is-spinning" size={14} /> : <RadioTower size={14} />}
                  {hostedProbeLoading ? "正在只读探测…" : hostedProbeReceipt ? "重新执行只读探测" : "执行只读探测"}
                </button>
              </div>

              {hostedProbeError ? <div className="hosted-transport-error" role="alert"><ShieldCheck size={15} /><span><strong>PROBE FAILED CLOSED</strong>{hostedProbeError}</span></div> : null}

              {hostedProbeReceipt ? (
                <article className="hosted-transport-receipt">
                  <header>
                    <div><small>IMMUTABLE PROBE RECEIPT</small><strong>{hostedProbeReceipt.operation_status}</strong></div>
                    <StatusBadge tone={hostedProbeReceipt.status === "PASS" ? "success" : hostedProbeReceipt.status === "FAIL" ? "danger" : "warning"} compact>{hostedProbeReceipt.status}</StatusBadge>
                  </header>
                  <dl>
                    <div><dt>operation</dt><dd>{hostedProbeReceipt.operation}</dd></div>
                    <div><dt>mode</dt><dd>{hostedProbeReceipt.mode}</dd></div>
                    <div><dt>controller</dt><dd>{String(hostedProbeReceipt.controller_connected)}</dd></div>
                    <div><dt>workers ready</dt><dd>{String(hostedProbeReceipt.workers_ready)}</dd></div>
                    <div><dt>remote execution</dt><dd>{String(hostedProbeReceipt.remote_task_execution_observed)}</dd></div>
                    <div><dt>hosted verified</dt><dd>{String(hostedProbeReceipt.hosted_runtime_verified)}</dd></div>
                  </dl>
                  <div className="hosted-transport-receipt__digest"><span>RECEIPT SHA-256</span><code>{hostedProbeReceipt.receipt_sha256}</code></div>
                  <p>{hostedProbeReceipt.boundary}</p>
                </article>
              ) : (
                <div className="hosted-transport-empty">
                  <ShieldCheck size={16} />
                  <span><strong>没有远程探测回执</strong><small>页面不会把 CONFIGURED 当作 CONNECTED，也不会自动补造 Hosted 证据。</small></span>
                </div>
              )}
            </section>
          ) : null}
        </section>
      ) : null}

      <section className="integration-domain-section">
        <header><div><span>IMPLEMENTED SURFACE</span><h2>真实接口域</h2></div><p>这些是已经存在的产品服务域，不代表外部系统身份已连接。</p></header>
        <div className="integration-domain-grid">
          {["Workspace / Project", "Data Source", "Task / Evidence", "Incident", "CAPA", "Annotation"].map((domain, index) => <article key={domain}><span>{String(index + 1).padStart(2, "0")}</span><strong>{domain}</strong><i /></article>)}
        </div>
      </section>

      <ClaimBoundary title="生态兼容边界" tone="warning">
        CVAT/FiftyOne 为 contract_ready_not_connected。Labelme、COCO、YOLO、MLflow、DVC 等只能通过 Adapter SDK 继续扩展，当前不能写成已逐一集成。
      </ClaimBoundary>
    </div>
  );
}
