import { ArrowRight, CheckCircle2, Database, FileCheck2, HardDrive, LoaderCircle, Network, RadioTower, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { AgentRuntimeCapabilities, HostedAgentTeamsReceipt, LocalTaskSource, SourceAuthorizationEvent } from "../agentDomain";
import { authorizeLocalTaskSource, getAgentRuntimeCapabilities, getHostedAgentTeamsHealthStatus, listLocalTaskSources, listSourceAuthorizationEvents, probeHostedAgentTeams, revokeLocalTaskSource, type HostedAgentTeamsHealthStatus } from "../data/api";
import { integrationCatalog } from "../data/integrationCatalog";
import { getIdentitySessionSnapshot, subscribeIdentitySession } from "../identitySession";
import { useProduct } from "../ProductContext";
import "../styles/control-surfaces.css";

const stateLabels: Record<string, string> = {
  LOCAL_CONTRACT_VERIFIED: "本地合同已验证", CONTRACT_READY_NOT_CONNECTED: "合同就绪 · 未连接",
  LOCAL_API_AVAILABLE: "本地 API 合同", ADAPTER_SDK_AVAILABLE: "可开发扩展", MAPPED_NOT_CONNECTED: "未连接", NOT_TESTED: "未测试",
};
const emptyForm = { displayName: "", rootPath: "", sourceArchiveSha256: "", purpose: "", rightsBasis: "", attested: false };
function shortDigest(value: string | null | undefined) { return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "未提供"; }

export function IntegrationsPage() {
  const { activeWorkspace, connection } = useProduct();
  const identity = useSyncExternalStore(subscribeIdentitySession, getIdentitySessionSnapshot, getIdentitySessionSnapshot);
  const workspaceId = activeWorkspace?.workspace_id;
  const scope = `${workspaceId ?? ""}:${identity.generation}:${connection.api}`;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const requestGeneration = useRef(0);
  const mutationInFlight = useRef(false);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [sources, setSources] = useState<LocalTaskSource[]>([]);
  const [verifiedScope, setVerifiedScope] = useState("");
  const [sourceState, setSourceState] = useState<"LOADING" | "VERIFIED" | "UNKNOWN">("UNKNOWN");
  const [sourceError, setSourceError] = useState<string>();
  const [sourceEvents, setSourceEvents] = useState<Record<string, SourceAuthorizationEvent[]>>({});
  const [eventError, setEventError] = useState<string>();
  const [runtimeCapabilities, setRuntimeCapabilities] = useState<AgentRuntimeCapabilities>();
  const [hostedHealthStatus, setHostedHealthStatus] = useState<HostedAgentTeamsHealthStatus>();
  const [capabilityError, setCapabilityError] = useState<string>();
  const [hostedProbeReceipt, setHostedProbeReceipt] = useState<HostedAgentTeamsReceipt>();
  const [hostedProbeLoading, setHostedProbeLoading] = useState(false);
  const [hostedProbeError, setHostedProbeError] = useState<string>();
  const [refreshToken, setRefreshToken] = useState(0);
  const [sourceForm, setSourceForm] = useState(emptyForm);
  const [sourceSubmitting, setSourceSubmitting] = useState(false);
  const [sourceFeedback, setSourceFeedback] = useState<string>();
  const [writeError, setWriteError] = useState<string>();
  const [revokingSourceId, setRevokingSourceId] = useState("");
  const [revokeReason, setRevokeReason] = useState("");
  const [revoking, setRevoking] = useState(false);
  const sourceVerified = sourceState === "VERIFIED" && verifiedScope === scope;
  const currentSources = sourceVerified ? sources : [];
  const activeSourceCount = currentSources.filter(source => source.status === "active").length;
  const canRead = Boolean(workspaceId) && connection.api === "CONNECTED";
  const canWrite = canRead && sourceVerified && !sourceSubmitting && !revoking && !writeError;

  useEffect(() => {
    setSourceForm(emptyForm); setSourceFeedback(undefined); setWriteError(undefined);
    setRevokingSourceId(""); setRevokeReason("");
  }, [workspaceId, identity.generation]);

  useEffect(() => {
    let active = true;
    const generation = ++requestGeneration.current;
    const current = () => active && generation === requestGeneration.current && scopeRef.current === scope;
    setSources([]); setVerifiedScope(""); setSourceEvents({}); setEventError(undefined);
    setSourceError(undefined); setRuntimeCapabilities(undefined); setHostedHealthStatus(undefined);
    setCapabilityError(undefined); setHostedProbeReceipt(undefined); setHostedProbeError(undefined);
    setHostedProbeLoading(false);
    if (!workspaceId || connection.api !== "CONNECTED") {
      setSourceState("UNKNOWN");
      return () => { active = false; };
    }
    setSourceState("LOADING");
    void Promise.allSettled([listLocalTaskSources(workspaceId), getAgentRuntimeCapabilities(), getHostedAgentTeamsHealthStatus()]).then(([sourceResult, capabilityResult, healthResult]) => {
      if (!current()) return;
      if (sourceResult.status === "fulfilled") {
        setSources(sourceResult.value); setVerifiedScope(scope); setSourceState("VERIFIED");
        void Promise.all(sourceResult.value.map(async source => [source.source_id, await listSourceAuthorizationEvents(source.source_id)] as const)).then(entries => {
          if (current()) setSourceEvents(Object.fromEntries(entries));
        }).catch(() => { if (current()) setEventError("授权事件尚未完整读取。重新读取来源可重试，不会重复登记或撤销。"); });
      } else { setSourceState("UNKNOWN"); setSourceError("无法读取来源清单。请检查本地服务与工作空间权限，再重新读取。"); }
      if (capabilityResult.status === "fulfilled") setRuntimeCapabilities(capabilityResult.value);
      if (healthResult.status === "fulfilled") setHostedHealthStatus(healthResult.value);
      if (capabilityResult.status === "rejected" || healthResult.status === "rejected") setCapabilityError("部分扩展配置未核实，不影响已成功读取的来源。");
    });
    return () => { active = false; };
  }, [scope, workspaceId, connection.api, refreshToken]);

  const visible = useMemo(() => integrationCatalog.filter(item => !query.trim() || `${item.name} ${item.category} ${item.protocol} ${item.capability}`.toLowerCase().includes(query.trim().toLowerCase())), [query]);
  const selected = integrationCatalog.find(item => item.id === selectedId);
  const hostedObservedStatus = hostedProbeReceipt?.operation_status
    ?? (hostedHealthStatus === "NOT_CONFIGURED" ? "NOT_CONFIGURED · 未配置" : hostedHealthStatus ?? "状态未核实");
  const reload = () => setRefreshToken(value => value + 1);

  async function authorizeSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspaceId || !canWrite || !sourceForm.attested || mutationInFlight.current) return;
    if (!/^[0-9a-f]{64}$/.test(sourceForm.sourceArchiveSha256)) { setSourceFeedback("发布归档摘要需要 64 位小写 SHA-256。"); return; }
    const requestScope = scope; const generation = requestGeneration.current;
    mutationInFlight.current = true; setSourceSubmitting(true); setSourceFeedback(undefined);
    try {
      const created = await authorizeLocalTaskSource({ workspaceId, displayName: sourceForm.displayName, rootPath: sourceForm.rootPath, sourceArchiveSha256: sourceForm.sourceArchiveSha256, purpose: sourceForm.purpose, rightsBasis: sourceForm.rightsBasis });
      if (scopeRef.current !== requestScope || generation !== requestGeneration.current) return;
      setSources(items => [created, ...items.filter(item => item.source_id !== created.source_id)]);
      setSourceFeedback(`已登记“${created.display_name}”。原始路径不会回显到来源回执中。`); setSourceForm(emptyForm);
    } catch {
      if (scopeRef.current === requestScope && generation === requestGeneration.current) setWriteError("登记结果未核实，已停止重复提交。请重新读取来源，按名称与归档摘要核对；在确认服务端结果前不要重复登记。");
    } finally { mutationInFlight.current = false; setSourceSubmitting(false); }
  }

  async function revokeSource(source: LocalTaskSource) {
    if (!canWrite || revokeReason.trim().length < 8 || mutationInFlight.current) return;
    const requestScope = scope; const generation = requestGeneration.current;
    mutationInFlight.current = true; setRevoking(true); setSourceFeedback(undefined);
    try {
      const event = await revokeLocalTaskSource({ sourceId: source.source_id, reason: revokeReason.trim(), expectedLatestEventSha256: source.latest_authorization_event_sha256 });
      if (scopeRef.current !== requestScope || generation !== requestGeneration.current) return;
      setSources(items => items.map(item => item.source_id === source.source_id ? { ...item, status: "revoked", authorization_event_count: item.authorization_event_count + 1, latest_authorization_event_sha256: event.event_sha256 } : item));
      setSourceEvents(items => ({ ...items, [source.source_id]: [...(items[source.source_id] ?? []), event] }));
      setSourceFeedback(`已撤销“${source.display_name}”，${event.fail_closed_task_ids.length} 个未开始任务已关闭。原始文件未删除。`); setRevokingSourceId(""); setRevokeReason("");
    } catch {
      if (scopeRef.current === requestScope && generation === requestGeneration.current) setWriteError("撤销结果未核实，已停止重复提交。请重新读取来源与授权事件，确认服务端的最终状态。");
    } finally { mutationInFlight.current = false; setRevoking(false); }
  }

  async function probeHostedTransport() {
    if (!workspaceId || !canRead || hostedHealthStatus !== "CONFIGURED_NOT_PROBED" || hostedProbeLoading) return;
    const requestScope = scope; const generation = requestGeneration.current;
    setHostedProbeLoading(true); setHostedProbeReceipt(undefined); setHostedProbeError(undefined);
    try {
      const receipt = await probeHostedAgentTeams(workspaceId);
      if (scopeRef.current === requestScope && generation === requestGeneration.current) setHostedProbeReceipt(receipt);
    } catch {
      if (scopeRef.current === requestScope && generation === requestGeneration.current) setHostedProbeError("远程只读探测未成功。未提交任何任务，请核对配置后重试。");
    } finally { if (scopeRef.current === requestScope && generation === requestGeneration.current) setHostedProbeLoading(false); }
  }

  return <div className="control-surface integration-controls">
    <header className="control-heading"><div><span className="control-kicker">{activeWorkspace?.name ?? "尚未选择工作空间"}</span><h1>数据来源与集成</h1><p>管理授权目录；模型和任务在各自工作区中操作。</p></div><Database size={23} aria-hidden="true" /></header>
    <div className="control-entry-row"><Link to="/workspace"><HardDrive size={17} /><span><strong>导入图片与数据集</strong><small>在图像工作簿上传、标注</small></span><ArrowRight size={15} /></Link><Link to="/models" aria-label="管理模型与 API"><Network size={17} /><span><strong>管理模型与 API</strong><small>本机模型、密钥与训练</small></span><ArrowRight size={15} /></Link><Link to="/command-center"><ShieldCheck size={17} /><span><strong>打开检查任务</strong><small>计划、工具回执与人工审批</small></span><ArrowRight size={15} /></Link></div>

    <section className="control-section" id="sources" aria-labelledby="sources-title">
      <header className="control-section-actions"><div><h2 id="sources-title">已授权来源</h2><p>{sourceVerified ? `${currentSources.length} 个来源 · ${activeSourceCount} 个有效授权` : "状态未确认时，不显示来源数量。"}</p></div><button type="button" className="control-button" disabled={!canRead || sourceState === "LOADING" || sourceSubmitting || revoking} onClick={reload}><RefreshCw size={14} className={sourceState === "LOADING" ? "is-spinning" : undefined} />重新读取来源</button></header>
      {sourceState === "LOADING" && canRead ? <p className="control-feedback" role="status">正在核验来源与授权状态…</p> : !sourceVerified ? <div className="control-feedback is-error" role="alert"><strong>来源清单未核实</strong><p>{sourceError ?? (!workspaceId ? "先选择工作空间，才能读取和登记来源。" : "本地 API 未连接。请在顶部重新检测服务，再读取来源。")}</p><small>UNKNOWN · 不等同于零来源</small></div> : currentSources.length === 0 ? <div className="control-empty"><HardDrive size={24} aria-hidden="true" /><h3>当前工作空间还没有授权来源。</h3><p>普通图片或数据集请先在工作簿导入。符合受控发布结构的目录可在下方登记。</p><Link to="/workspace">去工作簿导入</Link></div> : <div className="control-source-list">{currentSources.map(source => <article key={source.source_id}>
        <header><div><strong>{source.display_name}</strong><small>{source.adapter_kind}</small></div><span className={source.status === "active" ? "control-state is-active" : "control-state"}>{source.status === "active" ? "已授权" : source.status === "revoked" ? "已撤销" : source.status}</span></header>
        <dl className="control-facts"><div><dt>归档摘要</dt><dd><code title={source.source_archive_sha256}>{shortDigest(source.source_archive_sha256)}</code></dd></div><div><dt>登记时间</dt><dd>{new Date(source.created_at).toLocaleString()}</dd></div></dl>
        <details className="control-disclosure"><summary>来源 ID、完整摘要与授权历史</summary><code>{source.source_id}</code><code>{source.source_archive_sha256}</code><p>事件 {source.authorization_event_count} 条 · 最近事件 {shortDigest(source.latest_authorization_event_sha256)}</p>{sourceEvents[source.source_id] ? (sourceEvents[source.source_id] ?? []).map(event => <p key={event.event_id}><strong>#{event.sequence} {event.event_type}</strong> · {event.reason}<small>{event.actor_id} · {shortDigest(event.event_sha256)}</small></p>) : <p>事件历史尚未核实。</p>}</details>
        {source.status === "active" ? revokingSourceId === source.source_id ? <div className="control-revoke"><label>撤销原因（至少 8 字）<textarea aria-label="撤销原因" value={revokeReason} minLength={8} maxLength={1000} onChange={event => setRevokeReason(event.target.value)} disabled={revoking} /></label><p>撤销此来源的后续使用权限，不删除原始文件。受影响的未开始任务会停止。</p><div className="control-form-actions"><button type="button" onClick={() => { setRevokingSourceId(""); setRevokeReason(""); }} disabled={revoking}>保留授权</button><button type="button" className="is-danger" onClick={() => void revokeSource(source)} disabled={!canWrite || revokeReason.trim().length < 8}>{revoking ? "正在撤销…" : "永久撤销此授权"}</button></div></div> : <button type="button" className="control-text-button" disabled={!canWrite} onClick={() => setRevokingSourceId(source.source_id)}>撤销来源授权</button> : null}
      </article>)}</div>}
      {eventError ? <p className="control-feedback is-error" role="alert">{eventError}</p> : null}
      {sourceFeedback ? <p className="control-feedback" role="status">{sourceFeedback}</p> : null}
      {writeError ? <p className="control-feedback is-error" role="alert">{writeError}</p> : null}
      <details className="control-disclosure control-register"><summary><HardDrive size={16} /> 登记受控发布目录</summary><p>此入口适配 Omni-AD 受控发布目录（omni_ad_30_release），不是任意文件夹上传。原图留在服务端本地，登记仅授权只读使用。</p>
        <form className="control-source-form" onSubmit={event => void authorizeSource(event)}>
          <fieldset disabled={!canWrite}><legend>来源与使用授权</legend>
            <div className="control-form-grid"><label>显示名称<input required minLength={2} maxLength={120} value={sourceForm.displayName} onChange={event => setSourceForm(value => ({ ...value, displayName: event.target.value }))} /></label><label>服务端绝对目录<input required value={sourceForm.rootPath} onChange={event => setSourceForm(value => ({ ...value, rootPath: event.target.value }))} placeholder="填写已有受控发布目录" /></label></div>
            <label>发布归档 SHA-256<input required pattern="[0-9a-f]{64}" spellCheck={false} value={sourceForm.sourceArchiveSha256} onChange={event => setSourceForm(value => ({ ...value, sourceArchiveSha256: event.target.value.trim() }))} /><small>填写来源发布方提供或本地计算的完整归档摘要；不会替你编造摘要。</small></label>
            <div className="control-form-grid"><label>使用目的<textarea required minLength={8} maxLength={1000} rows={3} value={sourceForm.purpose} onChange={event => setSourceForm(value => ({ ...value, purpose: event.target.value }))} /></label><label>权利依据<textarea required minLength={8} maxLength={1000} rows={3} value={sourceForm.rightsBasis} onChange={event => setSourceForm(value => ({ ...value, rightsBasis: event.target.value }))} /></label></div>
            <label className="control-checkbox"><input type="checkbox" checked={sourceForm.attested} onChange={event => setSourceForm(value => ({ ...value, attested: event.target.checked }))} />我确认有权用于本地只读治理，不允许原图再分发。</label>
            <button type="submit" className="control-button is-primary" disabled={!canWrite || !sourceForm.attested}>{sourceSubmitting ? <LoaderCircle className="is-spinning" size={14} /> : <CheckCircle2 size={14} />}{sourceSubmitting ? "正在画像并登记…" : "登记只读来源"}</button>
          </fieldset>
          {!canWrite ? <p className="control-muted">{writeError ? "请先核对上一次写入结果，当前不接受重复提交。" : sourceSubmitting || revoking ? "等待当前操作返回结果。" : "需先成功读取当前工作空间来源，并保持本地 API 连接。"}</p> : null}
        </form>
      </details>
    </section>

    <details className="control-disclosure control-catalog"><summary><FileCheck2 size={16} /> 扩展合同目录</summary><p>这里说明可复用的接口和连接边界。浏览合同不会配置服务、运行 Agent 或提交任务。</p>
      {capabilityError ? <p className="control-feedback is-error">{capabilityError}</p> : null}
      <label className="control-search"><Search size={15} /><span className="sr-only">搜索扩展合同</span><input aria-label="搜索扩展合同" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索格式、接口或服务" /></label>
      <div className="control-catalog-list">{visible.map(item => <button type="button" key={item.id} aria-label={`查看合同与状态 · ${item.name}`} aria-pressed={selectedId === item.id} onClick={() => setSelectedId(item.id)}><span><strong>{item.name}</strong><small>{item.capability}</small></span><span>{stateLabels[item.state] ?? item.state}</span><ArrowRight size={14} /></button>)}</div>
      {visible.length === 0 ? <p>没有匹配的合同，请调整搜索词。</p> : null}
      {selected ? <section className="control-contract" id="integration-hub-inspector" aria-label="所选扩展合同"><h3>{selected.name}</h3><dl className="control-facts"><div><dt>协议</dt><dd>{selected.protocol}</dd></div><div><dt>能力</dt><dd>{selected.capability}</dd></div><div><dt>边界</dt><dd>{selected.boundary}</dd></div></dl>
        {selected.id === "external-models" ? <><p>{runtimeCapabilities ? `本地登记 ${runtimeCapabilities.model_profiles.length} 个运行配置；登记不代表已连接。` : "运行配置尚未核实。"}</p><Link to="/models">打开实际模型配置</Link></> : null}
        {selected.id === "local-source" ? <a href="#sources">返回授权来源</a> : null}
        {selected.id === "rest-api" ? <><p>当前本地 API：{connection.api}</p><Link to="/platform">查看平台运行能力</Link></> : null}
        {selected.id === "agentteams" ? <section className="control-hosted" aria-label="Hosted AgentTeams 受控传输"><small>HOSTED TRANSPORT CUSTODY</small><h4>可选 Hosted AgentTeams</h4><p>本地检查任务不依赖此连接。当前状态：{hostedObservedStatus}</p><p>打开页面只读取本地配置；点击后才连接远程服务进行只读探测，不提交任务。</p><button type="button" className="control-button" onClick={() => void probeHostedTransport()} disabled={hostedHealthStatus !== "CONFIGURED_NOT_PROBED" || hostedProbeLoading || !canRead}><RadioTower size={15} />{hostedProbeLoading ? "正在只读探测…" : "执行只读探测"}</button>{hostedHealthStatus !== "CONFIGURED_NOT_PROBED" ? <p className="control-muted">需由管理员先配置 Hosted 服务；当前没有可执行的远程探测。</p> : null}{hostedProbeError ? <p className="control-feedback is-error" role="alert">{hostedProbeError}</p> : null}{hostedProbeReceipt ? <div className="control-feedback" role="status"><strong>{hostedProbeReceipt.status} · {hostedProbeReceipt.operation_status}</strong><p>{hostedProbeReceipt.boundary}</p><dl className="control-facts"><div><dt>托管运行时已验证</dt><dd>{String(hostedProbeReceipt.hosted_runtime_verified)}</dd></div><div><dt>操作 / 模式</dt><dd>{hostedProbeReceipt.operation} / {hostedProbeReceipt.mode}</dd></div><div><dt>Controller 连接</dt><dd>{String(hostedProbeReceipt.controller_connected)}</dd></div><div><dt>Worker 就绪</dt><dd>{String(hostedProbeReceipt.workers_ready)}</dd></div><div><dt>远程执行观察</dt><dd>{String(hostedProbeReceipt.remote_task_execution_observed)}</dd></div></dl><code>{hostedProbeReceipt.receipt_sha256}</code></div> : null}</section> : null}
      </section> : null}
      <p className="control-muted">CVAT / FiftyOne 当前为合同就绪、未连接。其他格式的 Adapter SDK 能力不等于已完成外部集成。</p>
    </details>
  </div>;
}
