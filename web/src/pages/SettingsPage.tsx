import {
  AppWindow,
  Boxes,
  CheckCircle2,
  CircleDashed,
  CloudCog,
  Database,
  Eye,
  FolderOpen,
  Gauge,
  Globe2,
  KeyRound,
  Laptop,
  LockKeyhole,
  Palette,
  ServerCog,
  SlidersHorizontal,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ActionButton,
  ClaimBoundary,
  DetailRow,
  Panel,
  PanelHeader,
  StatusBadge,
  SystemHubHero,
} from "../components/ui";
import { ProviderCenter } from "../components/ProviderCenter";
import { operatorActorUserId } from "../data/api";
import { useInterfacePreferences, type AccentPalette } from "../interfacePreferences";
import { useLocalOperatorProfile } from "../localProfile";
import { useProduct } from "../ProductContext";
import {
  getPlatformCapability,
  openDesktopConfigDirectory,
  resolveDesktopRuntimeConfig,
  type DesktopRuntimeConfig,
} from "../platform/bridge";

const desktopTargets = [
  { name: "Windows x64", state: "DESKTOP TARGET", tone: "success" as const, detail: "Tauri 2 + 本地 FastAPI sidecar + NSIS" },
];

const accentOptions: Array<{ id: AccentPalette; label: string; detail: string; colors: string[] }> = [
  { id: "violet-cyan", label: "电光紫 × 冰川青", detail: "默认 · 冷峻科技", colors: ["#8b8cf8", "#55d6e8", "#b8ff70"] },
  { id: "cyan-lime", label: "深海青 × 荧光绿", detail: "诊断 · 高对比", colors: ["#32d5de", "#9de86b", "#ffd166"] },
  { id: "coral-violet", label: "珊瑚橙 × 星云紫", detail: "重点 · 强节奏", colors: ["#ff765f", "#a78bfa", "#5eead4"] },
];

export function SettingsPage() {
  const { connection } = useProduct();
  const { profile } = useLocalOperatorProfile();
  const { preferences, updatePreferences } = useInterfacePreferences();
  const navigate = useNavigate();
  const platform = getPlatformCapability();
  const [desktopRuntime, setDesktopRuntime] = useState<DesktopRuntimeConfig>();

  useEffect(() => {
    void resolveDesktopRuntimeConfig().then(setDesktopRuntime);
  }, []);

  return (
    <div className="page-stack settings-page">
      <nav className="settings-anchorbar system-hub-toolbar" aria-label="设置分区">
        <a className="is-active" href="#appearance"><Palette size={15} /> 外观</a>
        <a href="#runtime"><ServerCog size={15} /> 运行</a>
        <a href="#providers"><CloudCog size={15} /> 模型接入</a>
        <a href="#data"><Database size={15} /> 数据</a>
        <a href="#desktop"><Laptop size={15} /> 桌面交付</a>
        <button type="button" onClick={() => navigate("/account")}><UserRound size={15} /> 账户与会话</button>
        <span className="system-hub-toolbar__status"><i /> SAVED LOCALLY</span>
      </nav>

      <SystemHubHero
        eyebrow="SETTINGS / LOCAL PRODUCT CONTROL"
        title="设置与本机运行"
        description="把外观、运行时、客户模型、数据边界和桌面交付整理成可直接进入的配置工作流。"
        ariaLabel="设置能力分区"
        meta={<><span>{platform.platform}</span><span>{platform.runtime}</span><span>API {connection.api}</span></>}
        cards={[
          { id: "appearance", eyebrow: "APPEARANCE", title: "界面与工作密度", description: "调整撞色主题、阅读密度与动效。", status: preferences.density.toUpperCase(), tone: "cyan", icon: Palette, href: "#appearance", members: [
            { icon: Sparkles, title: "撞色主题", detail: preferences.accent },
            { icon: Gauge, title: "信息密度", detail: preferences.density },
            { icon: Eye, title: "减少动画", detail: preferences.reduceMotion ? "ENABLED" : "DISABLED" },
          ] },
          { id: "runtime", eyebrow: "LOCAL RUNTIME", title: "服务与本机身份", description: "读取当前前端、API 与操作者状态。", status: connection.api, tone: "violet", icon: ServerCog, href: "#runtime", members: [
            { icon: Globe2, title: "Frontend", detail: platform.runtime },
            { icon: ServerCog, title: "FastAPI", detail: connection.api },
            { icon: UserRound, title: profile.displayName, detail: operatorActorUserId },
          ] },
          { id: "providers", eyebrow: "MODEL PROVIDERS", title: "客户模型与 API Key", description: "接入 DeepSeek、OpenToken、OpenAI 或兼容模型。", status: "BYOK", tone: "cyan", icon: CloudCog, href: "#providers", members: [
            { icon: KeyRound, title: "API Key", detail: "仅输入与提交期间存在" },
            { icon: LockKeyhole, title: "本机密钥库", detail: "Windows DPAPI" },
            { icon: Boxes, title: "隔离范围", detail: "用户 × 工作区" },
          ] },
          { id: "data", eyebrow: "DATA & PRIVACY", title: "数据安全边界", description: "所有原图、样例和凭证按边界治理。", status: "ENFORCED", tone: "coral", icon: Database, href: "#data", members: [
            { icon: LockKeyhole, title: "原图外发", detail: "false" },
            { icon: Boxes, title: "项目与样例", detail: "严格分离" },
            { icon: AppWindow, title: "密钥明文持久化", detail: "false" },
          ] },
          { id: "desktop", eyebrow: "WINDOWS DELIVERY", title: "桌面交付合同", description: "当前只建设 Windows x64 目标。", status: platform.runtime === "TAURI" ? "ACTIVE" : "SOURCE READY", tone: "lime", icon: Laptop, href: "#desktop", members: [
            { icon: Laptop, title: "Windows x64", detail: "唯一桌面目标" },
            { icon: AppWindow, title: "Tauri 2", detail: platform.runtime === "TAURI" ? "ACTIVE" : "SOURCE READY" },
            { icon: CircleDashed, title: "NSIS 安装包", detail: "NOT BUILT" },
          ] },
        ]}
      />

      <section id="appearance" className="settings-section">
        <header><span><Sparkles size={15} /> APPEARANCE</span><h2>界面与工作密度</h2><p>让高密度工程信息保持层级，而不是把所有内容压成相同的蓝色框。</p></header>
        <div className="settings-grid settings-grid--appearance">
          <Panel variant="raised">
            <PanelHeader eyebrow="ACCENT SYSTEM" title="撞色主题" detail="改变导航焦点、强调线、状态光晕与关键动作色。" />
            <div className="accent-picker">
              {accentOptions.map((option) => (
                <button
                  type="button"
                  key={option.id}
                  className={preferences.accent === option.id ? "is-active" : ""}
                  onClick={() => updatePreferences({ accent: option.id })}
                  aria-pressed={preferences.accent === option.id}
                >
                  <span className="accent-picker__swatches">{option.colors.map((color) => <i key={color} style={{ background: color }} />)}</span>
                  <span><strong>{option.label}</strong><small>{option.detail}</small></span>
                  {preferences.accent === option.id ? <CheckCircle2 size={16} /> : <CircleDashed size={16} />}
                </button>
              ))}
            </div>
          </Panel>

          <Panel>
            <PanelHeader eyebrow="READING MODE" title="密度与动效" detail="即时应用于当前桌面工作台。" />
            <div className="settings-control-list">
              <div>
                <span><Gauge size={17} /><span><strong>信息密度</strong><small>紧凑模式减少系统页垂直间距。</small></span></span>
                <div className="settings-segmented">
                  <button type="button" className={preferences.density === "comfortable" ? "is-active" : ""} onClick={() => updatePreferences({ density: "comfortable" })}>舒适</button>
                  <button type="button" className={preferences.density === "compact" ? "is-active" : ""} onClick={() => updatePreferences({ density: "compact" })}>紧凑</button>
                </div>
              </div>
              <label className="settings-toggle">
                <span><Eye size={17} /><span><strong>减少动画</strong><small>关闭装饰脉冲与非必要过渡。</small></span></span>
                <input type="checkbox" checked={preferences.reduceMotion} onChange={(event) => updatePreferences({ reduceMotion: event.target.checked })} />
                <i />
              </label>
              <div className="settings-accent-preview" aria-hidden="true"><span>★ Evidence</span><strong>Agent is ready</strong><i /></div>
            </div>
          </Panel>
        </div>
      </section>

      <section id="runtime" className="settings-section">
        <header><span><ServerCog size={15} /> RUNTIME</span><h2>本机服务与身份</h2><p>状态来自当前运行时；已保存的密钥不会被服务端回填到页面。</p></header>
        <div className="settings-grid">
          <Panel variant="raised">
            <PanelHeader eyebrow="CURRENT RUNTIME" title="本地运行环境" detail="React 工作台与 FastAPI 权威数据层。" />
            <div className="platform-runtime">
              <span><Globe2 size={26} /></span>
              <div><small>Frontend runtime</small><strong>{platform.runtime}</strong><p>{connection.api === "CONNECTED" ? "本地 FastAPI 权威数据层" : "API 未连接 · 业务页不回退样例"}</p></div>
            </div>
            <DetailRow label="detected platform" value={platform.platform} />
            <DetailRow label="API" value={<StatusBadge tone={connection.api === "CONNECTED" ? "success" : "warning"}>{connection.api}</StatusBadge>} />
            <DetailRow label="Reviewer snapshot" value={connection.reviewer} />
            <DetailRow label="desktop packaging" value={platform.desktopPackaging} />
            {desktopRuntime ? <DetailRow label="local data root" value={desktopRuntime.dataRoot} /> : null}
            {desktopRuntime ? <DetailRow label="desktop config" value={desktopRuntime.configFile} /> : null}
            {desktopRuntime ? <ActionButton variant="secondary" icon={FolderOpen} onClick={() => void openDesktopConfigDirectory()}>打开本机配置目录</ActionButton> : null}
          </Panel>

          <Panel>
            <PanelHeader eyebrow="ACCOUNT ENTRY" title="本地身份与会话" detail="资料和凭证状态在独立账户页管理。" />
            <div className="settings-account-card">
              <span>{profile.displayName.slice(0, 1)}</span>
              <div><small>LOCAL OPERATOR</small><strong>{profile.displayName}</strong><p>{profile.role} · {profile.team}</p></div>
              <StatusBadge tone="info">{operatorActorUserId}</StatusBadge>
            </div>
            <DetailRow label="identity type" value="LOCAL ACTOR HEADER" />
            <DetailRow label="desktop session" value={desktopRuntime ? "PRESENT · VALUE HIDDEN" : "NOT ISSUED IN BROWSER"} />
            <DetailRow label="production auth" value={<StatusBadge tone="warning">NOT CONFIGURED</StatusBadge>} />
            <button className="settings-open-account" type="button" onClick={() => navigate("/account")}><KeyRound size={14} /> 打开账户与会话中心</button>
          </Panel>
        </div>
      </section>

      <ProviderCenter />

      <section id="data" className="settings-section">
        <header><span><Database size={15} /> DATA & PRIVACY</span><h2>数据与隐私边界</h2><p>项目数据来自用户导入；浏览器与桌面运行时保持相同的安全合同。</p></header>
        <div className="settings-privacy-rail">
          <article><span><LockKeyhole size={18} /></span><div><strong>原图默认不外发</strong><p>raw image transmission = false</p></div><StatusBadge tone="success">ENFORCED</StatusBadge></article>
          <article><span><Boxes size={18} /></span><div><strong>项目与样例分离</strong><p>用户工作对象不会由 fixture 自动替代。</p></div><StatusBadge tone="info">SCOPED</StatusBadge></article>
          <article><span><AppWindow size={18} /></span><div><strong>应用不持久化密钥</strong><p>Key 仅在密码框和提交请求中短暂存在，保存后立即清空且永不回显。</p></div><StatusBadge tone="success">NO PERSIST</StatusBadge></article>
        </div>
      </section>

      <section id="desktop" className="settings-section">
        <header><span><Laptop size={15} /> WINDOWS DELIVERY</span><h2>Windows 桌面交付</h2><p>当前不打包，只显示源码能力和仍需验证的交付门禁。</p></header>
        <div className="platform-grid">
          <Panel>
            <PanelHeader eyebrow="TARGET MATRIX" title="Windows only" detail="当前只建设与验收 Windows x64 桌面安装包。" />
            <div className="desktop-targets">
              {desktopTargets.map((target) => <article key={target.name}><span className="desktop-targets__icon"><Laptop size={19} /></span><div><strong>{target.name}</strong><small>{target.detail}</small></div><StatusBadge tone={target.tone}>{target.state}</StatusBadge></article>)}
            </div>
          </Panel>
          <Panel>
            <PanelHeader eyebrow="DELIVERY GATES" title="Tauri 2 封装合同" detail="安装、签名与 clean-machine 验收分别取证。" />
            <div className="desktop-roadmap">
              <article className="is-complete"><span><CheckCircle2 size={18} /></span><div><strong>平台无关 Web 核心</strong><small>React Router、相对资源、API base URL</small></div><StatusBadge tone="success">IN THIS BUILD</StatusBadge></article>
              <article className={platform.runtime === "TAURI" ? "is-complete" : undefined}><span>{platform.runtime === "TAURI" ? <CheckCircle2 size={18} /> : <CircleDashed size={18} />}</span><div><strong>Tauri bridge</strong><small>随机端口、会话令牌、健康等待与退出回收</small></div><StatusBadge tone={platform.runtime === "TAURI" ? "success" : "warning"}>{platform.runtime === "TAURI" ? "ACTIVE" : "SOURCE READY"}</StatusBadge></article>
              <article><span><CircleDashed size={18} /></span><div><strong>Windows installer</strong><small>unsigned NSIS、SHA-256 与干净机验证</small></div><StatusBadge tone="warning">NOT BUILT</StatusBadge></article>
            </div>
          </Panel>
        </div>
      </section>

      <div className="platform-contracts">
        <article><span><AppWindow size={19} /></span><strong>同一 UI</strong><p>桌面封装不复制第二套页面。</p></article>
        <article><span><ServerCog size={19} /></span><strong>同一服务合同</strong><p>FastAPI 保持权威数据源。</p></article>
        <article><span><SlidersHorizontal size={19} /></span><strong>本机偏好</strong><p>外观设置即时生效。</p></article>
        <article><span><LockKeyhole size={19} /></span><strong>明文不持久化</strong><p>React 只保留提交前的临时输入，服务端不回显。</p></article>
      </div>

      <ClaimBoundary title="设置与交付边界" tone="warning">
        当前桌面目标仅为 Windows x64。企业认证、代码签名、正式安装包与干净机验收均未完成，页面不会把源码就绪状态升级为正式发行。
      </ClaimBoundary>
    </div>
  );
}
