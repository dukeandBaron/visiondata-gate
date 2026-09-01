import {
  BadgeCheck,
  Fingerprint,
  KeyRound,
  Laptop,
  LockKeyhole,
  Save,
  ShieldAlert,
  UserRound,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { operatorActorUserId } from "../data/api";
import {
  operatorInitials,
  useLocalOperatorProfile,
  type LocalOperatorProfile,
} from "../localProfile";
import { getPlatformCapability, resolveDesktopRuntimeConfig, type DesktopRuntimeConfig } from "../platform/bridge";
import { useProduct } from "../ProductContext";
import {
  ClaimBoundary,
  DetailRow,
  Panel,
  PanelHeader,
  StatusBadge,
  SystemHubHero,
} from "../components/ui";

export function AccountPage() {
  const { connection, activeWorkspace } = useProduct();
  const { profile, saveProfile } = useLocalOperatorProfile();
  const [draft, setDraft] = useState<LocalOperatorProfile>(profile);
  const [feedback, setFeedback] = useState<string>();
  const [desktopRuntime, setDesktopRuntime] = useState<DesktopRuntimeConfig>();
  const platform = getPlatformCapability();

  useEffect(() => setDraft(profile), [profile]);
  useEffect(() => {
    void resolveDesktopRuntimeConfig().then(setDesktopRuntime);
  }, []);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const saved = saveProfile(draft);
    setDraft(saved);
    setFeedback("本机显示资料已保存；API Actor ID 与授权边界没有改变。");
  };

  return (
    <div className="page-stack account-page">
      <nav className="system-hub-toolbar" aria-label="账户中心分区">
        <a className="is-active" href="#identity"><UserRound size={15} /> 身份</a>
        <a href="#profile"><Save size={15} /> 本机资料</a>
        <a href="#session"><KeyRound size={15} /> 会话凭证</a>
        <a href="#authority"><Fingerprint size={15} /> 人工权限</a>
        <span className="system-hub-toolbar__status"><i /> {platform.runtime}</span>
      </nav>

      <SystemHubHero
        eyebrow="ACCOUNT / LOCAL IDENTITY / SESSION"
        title="账户与会话中心"
        description="按身份、会话、权限和安全边界组织当前设备上的操作者上下文。"
        ariaLabel="账户与会话能力"
        meta={<><span>LOCAL ACTOR</span><span>{desktopRuntime ? "DESKTOP SESSION" : "BROWSER SESSION"}</span><span>PRODUCTION AUTH · OFF</span></>}
        cards={[
          { id: "identity", eyebrow: "LOCAL IDENTITY", title: "本机操作者", description: "让工作台动作具备明确署名。", status: "LOADED", tone: "cyan", icon: UserRound, href: "#identity", members: [
            { icon: BadgeCheck, title: profile.displayName, detail: `${profile.role} · ${profile.team}` },
            { icon: Fingerprint, title: "Actor Header", detail: operatorActorUserId },
            { icon: Laptop, title: "当前工作空间", detail: activeWorkspace?.name ?? "尚未选择" },
          ] },
          { id: "session", eyebrow: "SESSION CREDENTIALS", title: "会话与凭证", description: "只显示状态，不把密钥放进页面。", status: desktopRuntime ? "PRESENT" : "BROWSER", tone: "violet", icon: KeyRound, href: "#session", members: [
            { icon: UserRound, title: "API Actor", detail: "可追溯请求身份" },
            { icon: Laptop, title: "Desktop Token", detail: desktopRuntime ? "VALUE HIDDEN" : "NOT ISSUED" },
            { icon: LockKeyhole, title: "DOM Safety", detail: "credentials = false" },
          ] },
          { id: "authority", eyebrow: "HUMAN AUTHORITY", title: "具名人工闸门", description: "高责任动作必须重新确认。", status: "HUMAN ONLY", tone: "coral", icon: Fingerprint, href: "#authority", members: [
            { icon: BadgeCheck, title: "CAPA 审批", detail: "具名复核人与说明" },
            { icon: ShieldAlert, title: "生产认证", detail: "NOT CONFIGURED" },
            { icon: LockKeyhole, title: "设备写入", detail: "DENIED" },
          ] },
          { id: "boundary", eyebrow: "ACCOUNT BOUNDARY", title: "单机账户边界", description: "不把本机资料伪装成企业登录。", status: "LOCAL ONLY", tone: "lime", icon: ShieldAlert, href: "#account-boundary", members: [
            { icon: Save, title: "资料保存", detail: "当前设备" },
            { icon: KeyRound, title: "OAuth / SSO", detail: "NOT AVAILABLE" },
            { icon: UserRound, title: "多租户组织", detail: "NOT AVAILABLE" },
          ] },
        ]}
      />

      <div className="account-identity-hero" id="identity">
        <div className="account-avatar" aria-hidden="true">{operatorInitials(profile)}</div>
        <div>
          <span>LOCAL OPERATOR</span>
          <h2>{profile.displayName}</h2>
          <p>{profile.role} · {profile.team}</p>
        </div>
        <div className="account-trust-stack">
          <span className="is-safe"><BadgeCheck size={15} /> 本地身份已加载</span>
          <span className={desktopRuntime ? "is-safe" : "is-neutral"}><Laptop size={15} /> {desktopRuntime ? "桌面会话已建立" : "浏览器本地会话"}</span>
          <span className="is-warning"><ShieldAlert size={15} /> 生产认证未配置</span>
        </div>
      </div>

      <div className="account-grid">
        <Panel variant="raised" id="profile">
          <PanelHeader eyebrow="PROFILE / THIS DEVICE" title="本机显示资料" detail="仅保存在当前设备，用于界面署名；不会改写后端 Actor ID。" />
          <form className="account-profile-form" onSubmit={submit}>
            <label><span>显示名称</span><input required minLength={2} value={draft.displayName} onChange={(event) => setDraft((current) => ({ ...current, displayName: event.target.value }))} /></label>
            <label><span>岗位 / 职责</span><input required minLength={2} value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))} /></label>
            <label><span>团队 / 组织</span><input required minLength={2} value={draft.team} onChange={(event) => setDraft((current) => ({ ...current, team: event.target.value }))} /></label>
            {feedback ? <p className="account-feedback"><BadgeCheck size={14} /> {feedback}</p> : null}
            <button type="submit"><Save size={14} /> 保存本机资料</button>
          </form>
        </Panel>

        <Panel id="session">
          <PanelHeader eyebrow="IDENTITY BOUNDARIES" title="身份与会话凭证" detail="这里显示凭证状态，不读取或暴露密钥内容。" />
          <div className="account-session-map">
            <article>
              <span><UserRound size={18} /></span>
              <div><small>LOCAL IDENTITY</small><strong>Actor request header</strong><p>本地 API 的可追溯操作者标识。</p></div>
              <StatusBadge tone="info">ACTIVE</StatusBadge>
            </article>
            <article>
              <span><KeyRound size={18} /></span>
              <div><small>DESKTOP SESSION</small><strong>随机本机会话令牌</strong><p>仅在 Tauri 启动 sidecar 时建立。</p></div>
              <StatusBadge tone={desktopRuntime ? "success" : "locked"}>{desktopRuntime ? "PRESENT" : "NOT ISSUED"}</StatusBadge>
            </article>
            <article>
              <span><LockKeyhole size={18} /></span>
              <div><small>PRODUCTION AUTH</small><strong>企业登录 / OAuth / SSO</strong><p>当前没有后端认证服务，不伪造登录成功。</p></div>
              <StatusBadge tone="warning">NOT CONFIGURED</StatusBadge>
            </article>
          </div>
          <DetailRow label="actor_user_id" value={operatorActorUserId} />
          <DetailRow label="API transport" value={connection.api} />
          <DetailRow label="credentials in DOM" value="false" />
          <DetailRow label="desktop session token" value={desktopRuntime ? "PRESENT · VALUE HIDDEN" : "NOT ISSUED IN BROWSER"} />
        </Panel>
      </div>

      <div className="account-authority-band" id="authority">
        <Fingerprint size={22} />
        <div><strong>具名动作仍需当次人工确认</strong><p>本机资料不能替代 CAPA 审批中的复核人姓名、工号、说明与安全确认。</p></div>
        <StatusBadge tone="success">HUMAN AUTHORITY</StatusBadge>
      </div>

      <div id="account-boundary">
        <ClaimBoundary title="账户能力边界" tone="warning">
          当前实现是单机本地身份与桌面会话中心，不是多租户用户系统。密码登录、组织成员、OAuth/SSO、服务端会话撤销和权限管理，需要新增后端认证域后才能声明完成。
        </ClaimBoundary>
      </div>
    </div>
  );
}
