import { Fingerprint, KeyRound, LogOut, RefreshCw, ShieldCheck, UserPlus } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useIdentity } from "../IdentityContext";
import { useProduct } from "../ProductContext";
import { clearIdentitySession, type IdentityPublicUser } from "../identitySession";
import { OperatorApiError } from "../data/api";
import { addIdentityWorkspaceMember, approveIdentityUser, identityErrorMessage, listIdentitySessions,
  listIdentityUsers, listIdentityWorkspaceMembers, removeIdentityWorkspaceMember, revokeIdentitySession,
  updateIdentityUserRole, updateIdentityUserStatus, createIdentityWorkspace, type IdentitySessionRecord,
  type IdentityWorkspaceMember } from "../data/identityApi";
import { DetailRow, Panel, PanelHeader, StatusBadge } from "../components/ui";

function date(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}
function UserStatus({ status }: { status: IdentityPublicUser["status"] }) {
  return <StatusBadge tone={status === "ACTIVE" ? "success" : status === "PENDING" ? "warning" : "locked"}>
    {status === "ACTIVE" ? "已启用" : status === "PENDING" ? "待审批" : "已禁用"}
  </StatusBadge>;
}
function useAccountRows<T>(load: () => Promise<T[]>) {
  const [rows, setRows] = useState<T[]>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const sequence = useRef(0);
  const reload = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true); setError(undefined); setRows(undefined);
    try {
      const next = await load();
      if (sequence.current === current) setRows(next);
    } catch (failure) {
      if (sequence.current === current) setError(identityErrorMessage(failure));
    } finally { if (sequence.current === current) setLoading(false); }
  }, [load]);
  useEffect(() => { void reload(); return () => { sequence.current += 1; }; }, [reload]);
  return { rows, loading, error, reload };
}
function RefreshButton({ refresh, disabled }: { refresh: () => Promise<void>; disabled: boolean }) {
  return <button className="identity-button identity-button--compact" disabled={disabled} onClick={() => void refresh()}><RefreshCw size={13} /> 刷新</button>;
}
function Message({ error }: { error?: string }) {
  return error ? <div className="identity-panel-message"><p className="identity-feedback identity-feedback--error" role="alert">{error}</p></div> : null;
}

function SessionsPanel() {
  const source = useAccountRows<IdentitySessionRecord>(listIdentitySessions);
  const [selected, setSelected] = useState<IdentitySessionRecord>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const revoke = async () => {
    if (!selected || busy) return;
    setBusy(true); setError(undefined);
    try {
      await revokeIdentitySession(selected.session_id);
      if (selected.is_current) { clearIdentitySession(); return; }
      setSelected(undefined); await source.reload();
    } catch (failure) { setError(identityErrorMessage(failure)); }
    finally { setBusy(false); }
  };
  return <Panel id="sessions"><PanelHeader eyebrow="SERVER SESSIONS" title="登录会话" detail="只显示非秘密会话编号。撤销后，该会话不能继续访问业务接口。"
    actions={<RefreshButton refresh={source.reload} disabled={source.loading || busy} />} />
    <Message error={error || source.error} />
    {selected ? <div className="identity-confirm"><div><strong>{selected.is_current ? "撤销当前会话并退出？" : "撤销这条登录会话？"}</strong><p>服务器确认后生效。此操作不会删除工作区、任务或数据。</p></div><div><button className="identity-button" disabled={busy} onClick={() => setSelected(undefined)}>取消</button><button className="identity-button identity-button--danger" disabled={busy} onClick={() => void revoke()}>确认撤销</button></div></div> : null}
    {source.loading ? <p className="identity-empty" role="status">正在读取服务端会话…</p> : source.rows?.length === 0 ? <p className="identity-empty">服务端未返回会话记录。请刷新状态后检查。</p> : source.rows ? <div className="identity-table-wrap"><table className="identity-table"><thead><tr><th>会话</th><th>创建时间</th><th>到期时间</th><th>操作</th></tr></thead><tbody>{source.rows.map((session) => <tr key={session.session_id}><td><strong>{session.is_current ? "当前会话" : session.revoked_at ? "已撤销" : "其他会话"}</strong><small>{session.session_id}</small></td><td>{date(session.created_at)}</td><td>{date(session.expires_at)}</td><td><button className="identity-button identity-button--compact" disabled={busy || Boolean(session.revoked_at)} onClick={() => { setSelected(session); setError(undefined); }}>撤销</button></td></tr>)}</tbody></table></div> : null}
  </Panel>;
}

type AdminAction = { user: IdentityPublicUser; kind: "approve" | "disable" | "enable" | "promote" | "demote" };
const adminLabels: Record<AdminAction["kind"], string> = { approve: "批准注册", disable: "禁用账户", enable: "启用账户", promote: "授予平台管理员", demote: "改为普通用户" };
function AdminUsersPanel({ actorId }: { actorId: string }) {
  const source = useAccountRows<IdentityPublicUser>(listIdentityUsers);
  const [selected, setSelected] = useState<AdminAction>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const apply = async () => {
    if (!selected || busy) return;
    setBusy(true); setError(undefined);
    try {
      const id = selected.user.user_id;
      if (selected.kind === "approve") await approveIdentityUser(id);
      else if (selected.kind === "disable" || selected.kind === "enable") await updateIdentityUserStatus(id, selected.kind === "disable" ? "DISABLED" : "ACTIVE");
      else await updateIdentityUserRole(id, selected.kind === "promote" ? "ADMIN" : "USER");
      setSelected(undefined); await source.reload();
    } catch (failure) { setError(identityErrorMessage(failure)); }
    finally { setBusy(false); }
  };
  const select = (user: IdentityPublicUser, kind: AdminAction["kind"]) => { setSelected({ user, kind }); setError(undefined); };
  return <Panel id="users"><PanelHeader eyebrow="ADMINISTRATION" title="用户管理" detail="注册申请默认待审批。平台管理员管理账户，不自动拥有所有工作区，也不能查看其他人的模型密钥。"
    actions={<RefreshButton refresh={source.reload} disabled={source.loading || busy} />} />
    <Message error={error || source.error} />
    {selected ? <div className="identity-confirm"><div><strong>{adminLabels[selected.kind]}：{selected.user.display_name}（{selected.user.login_name}）？</strong><p>{selected.kind === "disable" ? "禁用将撤销该用户的登录会话；不会删除其数据。" : selected.kind === "approve" ? "审批仅启用账户，不会授予已有工作区权限。" : "账户管理权限与工作区成员权限相互独立。"}</p></div><div><button className="identity-button" disabled={busy} onClick={() => setSelected(undefined)}>取消</button><button className="identity-button identity-button--primary" disabled={busy} onClick={() => void apply()}>确认{adminLabels[selected.kind]}</button></div></div> : null}
    {source.loading ? <p className="identity-empty" role="status">正在读取用户列表…</p> : source.rows?.length === 0 ? <p className="identity-empty">没有可显示的账户记录。</p> : source.rows ? <div className="identity-table-wrap"><table className="identity-table"><thead><tr><th>用户</th><th>平台身份</th><th>状态</th><th>操作</th></tr></thead><tbody>{source.rows.map((user) => <tr key={user.user_id}><td><strong>{user.display_name}{user.user_id === actorId ? " · 当前账户" : ""}</strong><small>{user.login_name} · {user.user_id}</small></td><td>{user.platform_role === "ADMIN" ? "平台管理员" : "普通用户"}</td><td><UserStatus status={user.status} /></td><td><div className="identity-table__actions">
      {user.status === "PENDING" ? <button className="identity-button identity-button--compact" disabled={busy} onClick={() => select(user, "approve")}>批准注册</button> : <button className="identity-button identity-button--compact" disabled={busy || user.user_id === actorId} title={user.user_id === actorId ? "不在此处禁用当前账户" : undefined} onClick={() => select(user, user.status === "ACTIVE" ? "disable" : "enable")}>{user.status === "ACTIVE" ? "禁用" : "启用"}</button>}
      {user.status === "ACTIVE" ? <button className="identity-button identity-button--compact" disabled={busy || user.user_id === actorId} onClick={() => select(user, user.platform_role === "ADMIN" ? "demote" : "promote")}>{user.platform_role === "ADMIN" ? "移除管理员" : "设为管理员"}</button> : null}
    </div></td></tr>)}</tbody></table></div> : null}
    <p className="identity-empty">新成员先在登录页提交注册申请，再由管理员审批。工作区所有者随后按用户 ID 单独授权。</p>
  </Panel>;
}

function MembersPanel({ workspaceId, workspaceName, owner }: { workspaceId: string; workspaceName: string; owner: boolean }) {
  const load = useCallback(() => listIdentityWorkspaceMembers(workspaceId), [workspaceId]);
  const source = useAccountRows<IdentityWorkspaceMember>(load);
  const [userId, setUserId] = useState("");
  const [selected, setSelected] = useState<{ kind: "add" | "remove"; userId: string; name: string }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const requestAdd = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(undefined);
    const id = userId.trim();
    if (source.rows?.some((member) => member.user_id === id)) { setError("此用户已经是当前工作区成员。"); return; }
    setSelected({ kind: "add", userId: id, name: id });
  };
  const apply = async () => {
    if (!selected || busy || !owner) return;
    setBusy(true); setError(undefined);
    try {
      if (selected.kind === "add") await addIdentityWorkspaceMember(workspaceId, selected.userId);
      else await removeIdentityWorkspaceMember(workspaceId, selected.userId);
      const members = await listIdentityWorkspaceMembers(workspaceId);
      const exists = members.some((member) => member.user_id === selected.userId);
      if (exists !== (selected.kind === "add")) { setError("写入结果未在成员清单中确认。请手动刷新，不要重复授权。"); return; }
      setSelected(undefined); setUserId(""); await source.reload();
    } catch (failure) { setError(identityErrorMessage(failure)); }
    finally { setBusy(false); }
  };
  return <Panel id="members"><PanelHeader eyebrow="WORKSPACE MEMBERSHIP" title={`${workspaceName} · 工作区成员`} detail={owner ? "你是当前工作区所有者。只能为已启用账户授予 member 权限；member 不是只读角色。" : "只有当前工作区所有者可以添加或移除成员。平台管理员身份不能代替工作区所有权。"}
    actions={<RefreshButton refresh={source.reload} disabled={source.loading || busy} />} />
    <Message error={error || source.error} />
    {owner ? <form className="identity-member-form" onSubmit={requestAdd}><label htmlFor="identity-member-id">已启用账户的用户 ID<input id="identity-member-id" value={userId} onChange={(event) => setUserId(event.target.value)} required maxLength={256} disabled={busy} placeholder="usr_…" autoComplete="off" /></label><button className="identity-button" type="submit" disabled={busy || source.loading}><UserPlus size={14} /> 添加成员</button><small>用户可在自己的账户页找到 ID；没有“注册即进入现有工作区”或“自选 owner”路径。</small></form> : null}
    {selected ? <div className="identity-confirm"><div><strong>{selected.kind === "add" ? "授权加入" : "移除成员"}：{selected.name}？</strong><p>{selected.kind === "add" ? "将获得当前工作区的成员读写权限。不会改变工作区所有者。" : "将失去当前工作区访问权限；不会删除该用户或历史任务。"}</p></div><div><button className="identity-button" disabled={busy} onClick={() => setSelected(undefined)}>取消</button><button className="identity-button identity-button--primary" disabled={busy} onClick={() => void apply()}>确认{selected.kind === "add" ? "授权" : "移除"}</button></div></div> : null}
    {source.loading ? <p className="identity-empty" role="status">正在读取成员权限…</p> : source.rows?.length === 0 ? <p className="identity-empty">服务端未返回成员记录。请检查当前工作区。</p> : source.rows ? <div className="identity-table-wrap"><table className="identity-table"><thead><tr><th>成员</th><th>工作区角色</th><th>管理</th></tr></thead><tbody>{source.rows.map((member) => <tr key={member.user_id}><td><strong>{member.display_name}</strong><small>{member.user_id}</small></td><td>{member.role === "owner" ? "所有者" : "成员 · 非只读"}</td><td>{owner && member.role !== "owner" ? <button className="identity-button identity-button--compact" disabled={busy} onClick={() => { setSelected({ kind: "remove", userId: member.user_id, name: member.display_name }); setError(undefined); }}>移除</button> : <span>—</span>}</td></tr>)}</tbody></table></div> : null}
  </Panel>;
}

function PasswordPanel() {
  const identity = useIdentity();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string>();
  const change = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(undefined);
    if (identity.busy) return;
    if (next !== confirmation) { setError("两次输入的新密码不一致。"); return; }
    const input = { current_password: current, new_password: next };
    setCurrent(""); setNext(""); setConfirmation("");
    await identity.password(input);
  };
  return <Panel><PanelHeader eyebrow="PASSWORD" title="修改密码" detail="成功后撤销全部旧会话，并要求使用新密码重新登录。" />
    <form className="identity-form" onSubmit={(event) => void change(event)}>
      <label htmlFor="identity-current-password">当前密码<input id="identity-current-password" type="password" autoComplete="current-password" required minLength={12} maxLength={256} value={current} onChange={(event) => setCurrent(event.target.value)} disabled={identity.busy} /></label>
      <label htmlFor="identity-new-password">新密码<input id="identity-new-password" aria-label="新密码" aria-describedby="identity-new-password-hint" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={next} onChange={(event) => setNext(event.target.value)} disabled={identity.busy} /><small id="identity-new-password-hint">12–256 个字符，输入中的空格原样保留。</small></label>
      <label htmlFor="identity-confirm-password">再次输入新密码<input id="identity-confirm-password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={identity.busy} /></label>
      {error || identity.error ? <p className="identity-feedback identity-feedback--error" role="alert">{error || identity.error}</p> : null}
      <button type="submit" className="identity-button" disabled={identity.busy}><KeyRound size={14} /> 修改密码并退出旧会话</button>
    </form></Panel>;
}

function CreateWorkspacePanel({ userId }: { userId: string }) {
  const { refreshWorkspaceScope, workspaces } = useProduct();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<string>();
  const [createdId, setCreatedId] = useState<string>();
  const inFlight = useRef(false);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (inFlight.current || locked) return;
    inFlight.current = true; setBusy(true); setLocked(true); setError(undefined);
    try {
      const created = await createIdentityWorkspace(name, userId);
      setCreatedId(created.workspace_id);
      await refreshWorkspaceScope();
    } catch (failure) {
      setError(identityErrorMessage(failure));
      // Only an explicit rejecting 4xx is safe to correct and submit again.
      if (failure instanceof OperatorApiError && [400, 401, 403, 409, 422, 429].includes(failure.status)) setLocked(false);
    } finally { inFlight.current = false; setBusy(false); }
  };
  const refresh = async () => {
    if (busy) return;
    setBusy(true);
    try { await refreshWorkspaceScope(); } catch (failure) { setError(identityErrorMessage(failure)); }
    finally { setBusy(false); }
  };
  return <Panel id="create-workspace"><PanelHeader eyebrow="YOUR OWN WORKSPACE" title="新建我的工作区" detail="显式创建一个由当前登录账户拥有的新空间。不会加入、认领或更改其他人的已有工作区。" />
    <form className="identity-member-form" onSubmit={(event) => void create(event)}><label htmlFor="identity-workspace-name">新工作区名称<input id="identity-workspace-name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} disabled={busy || locked} /></label><button className="identity-button" type="submit" disabled={busy || locked}><UserPlus size={14} /> 创建我的工作区</button><small>所有者来自当前已认证的用户 ID，不能选择或填写其他人。</small></form>
    <Message error={error} />
    {createdId ? <div className="identity-panel-message"><p className="identity-feedback" role="status">已确认新工作区：{createdId}。{workspaces?.some((workspace) => workspace.workspace_id === createdId) ? "工作区列表已更新。" : "请刷新工作区列表，按此 ID 核对。"}</p></div> : locked ? <div className="identity-panel-message"><p className="identity-feedback" role="alert">尚未确认创建结果，已锁定本次提交。请刷新工作区列表并核对；同名不是唯一凭据，不会自动按名称判断成功或重复创建。</p></div> : null}
    {locked ? <div className="identity-panel-message"><button className="identity-button" disabled={busy} onClick={() => void refresh()}><RefreshCw size={14} /> 刷新工作区列表</button></div> : null}
  </Panel>;
}

export function AccountPage() {
  const identity = useIdentity();
  const { activeWorkspace } = useProduct();
  const user = identity.user;
  if (!user) return <p className="identity-empty">用户会话尚未确认，请从登录入口重新进入。</p>;
  return <div className="page-stack identity-account" data-testid="identity-account-page">
    <header className="identity-account__heading"><div><span className="identity-eyebrow">ACCOUNT / SESSIONS / ACCESS</span><h1>账户与权限</h1><p>管理真实登录账户、服务端会话，以及当前工作区的成员范围。</p></div><button className="identity-button" disabled={identity.busy} onClick={() => void identity.logout()}><LogOut size={14} /> 退出登录</button></header>
    <div className="identity-account__summary"><div className="identity-account__avatar" aria-hidden="true">{Array.from(user.display_name).slice(0, 2).join("").toUpperCase()}</div><div><h2>{user.display_name}</h2><p>{user.login_name} · {user.platform_role === "ADMIN" ? "平台管理员" : "普通用户"}</p></div><UserStatus status={user.status} /></div>
    <div className="identity-account__columns"><Panel><PanelHeader eyebrow="AUTHENTICATED USER" title="服务端身份" detail="以下资料来自登录响应，不是浏览器保存的显示名称。" /><div className="identity-account__details"><DetailRow label="用户 ID" value={user.user_id} /><DetailRow label="登录名" value={user.login_name} /><DetailRow label="邮箱" value={user.email || "未填写"} /><DetailRow label="创建时间" value={date(user.created_at)} /><DetailRow label="平台角色" value={user.platform_role === "ADMIN" ? "管理员" : "普通用户"} /><DetailRow label="当前工作区" value={activeWorkspace?.name || "尚无已授权工作区"} /><DetailRow label="认证范围" value="本地密码账户 · 非 OAuth / SSO" /><DetailRow label="浏览器令牌持久化" value="关闭；仅当前页面内存" /></div></Panel><PasswordPanel /></div>
    <SessionsPanel />
    <CreateWorkspacePanel userId={user.user_id} />
    {user.platform_role === "ADMIN" ? <AdminUsersPanel actorId={user.user_id} /> : null}
    {activeWorkspace?.role === "owner" ? <MembersPanel key={activeWorkspace.workspace_id} workspaceId={activeWorkspace.workspace_id} workspaceName={activeWorkspace.name} owner /> : <Panel><PanelHeader title="工作区访问" detail={activeWorkspace ? `${activeWorkspace.name} · 当前角色为成员，非只读权限。` : "此账户尚未进入已授权工作区。"} /><p className="identity-empty">只有工作区所有者可以查看和管理成员清单。将上方用户 ID 提供给工作区所有者；注册审批与工作区授权是两个独立步骤。</p></Panel>}
    <aside className="identity-account__boundary"><Fingerprint size={20} /><div><strong>真实登录不替代当次人工审批</strong><p>CAPA、数据释放和高责任动作仍需具名复核与安全确认。账户角色不能提升质量闸门结论，也不允许越过数据源授权。本地账户管理不是企业 SSO、可信签名或生产身份认证部署证明。</p></div><ShieldCheck size={18} /></aside>
  </div>;
}
