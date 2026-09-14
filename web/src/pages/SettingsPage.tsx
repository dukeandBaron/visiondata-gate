import { Check, FolderOpen, LoaderCircle, Monitor, SlidersHorizontal } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { useInterfacePreferences, type AccentPalette } from "../interfacePreferences";
import { getIdentitySessionSnapshot, subscribeIdentitySession } from "../identitySession";
import { useProduct } from "../ProductContext";
import { getPlatformCapability, openDesktopConfigDirectory, resolveDesktopRuntimeConfig, type DesktopRuntimeConfig } from "../platform/bridge";
import "../styles/control-surfaces.css";

const accentOptions: Array<{ id: AccentPalette; label: string; colors: string[] }> = [
  { id: "graphite", label: "石墨 · 中性", colors: ["#292a2d", "#c9b58e"] },
  { id: "violet-cyan", label: "紫青", colors: ["#8b8cf8", "#55d6e8"] },
  { id: "cyan-lime", label: "青绿", colors: ["#32d5de", "#9de86b"] },
  { id: "coral-violet", label: "珊瑚紫", colors: ["#ff765f", "#a78bfa"] },
];

export function SettingsPage() {
  const { connection } = useProduct();
  const account = useSyncExternalStore(subscribeIdentitySession, getIdentitySessionSnapshot, getIdentitySessionSnapshot);
  const { preferences, updatePreferences } = useInterfacePreferences();
  const platform = getPlatformCapability();
  const [desktopRuntime, setDesktopRuntime] = useState<DesktopRuntimeConfig>();
  const [runtimeLoading, setRuntimeLoading] = useState(platform.runtime === "TAURI");
  const [runtimeError, setRuntimeError] = useState<string>();
  const [runtimeAttempt, setRuntimeAttempt] = useState(0);
  const [opening, setOpening] = useState(false);
  const [directoryMessage, setDirectoryMessage] = useState<{ failed: boolean; text: string }>();

  useEffect(() => {
    let current = true;
    setRuntimeLoading(platform.runtime === "TAURI");
    setRuntimeError(undefined);
    void resolveDesktopRuntimeConfig().then(value => {
      if (current) setDesktopRuntime(value);
    }).catch(() => {
      if (current) { setDesktopRuntime(undefined); setRuntimeError("无法读取桌面配置。请确认本机服务正在运行后重试。"); }
    }).finally(() => { if (current) setRuntimeLoading(false); });
    return () => { current = false; };
  }, [platform.runtime, runtimeAttempt]);

  async function openDirectory() {
    if (opening || !desktopRuntime) return;
    setOpening(true);
    setDirectoryMessage(undefined);
    try {
      await openDesktopConfigDirectory();
      setDirectoryMessage({ failed: false, text: "已请求系统打开配置目录。" });
    } catch {
      setDirectoryMessage({ failed: true, text: "未能打开配置目录。请确认目录可访问，再点击重试；也可复制下方路径手动打开。" });
    } finally { setOpening(false); }
  }

  return <div className="control-surface settings-controls">
    <header className="control-heading"><div><span className="control-kicker">本机偏好</span><h1>设置</h1><p>调整阅读方式，查看当前会话和本机服务。</p></div><SlidersHorizontal size={22} aria-hidden="true" /></header>
    <nav className="control-jump-links" aria-label="设置分区"><a href="#appearance">外观</a><a href="#runtime">本机服务</a><a href="#providers">模型与 API</a><a href="#data">隐私边界</a><a href="#desktop">Windows 桌面</a></nav>

    <section id="appearance" className="control-section" aria-labelledby="appearance-title">
      <header><h2 id="appearance-title">外观与阅读</h2><p>偏好在本机保存，即时生效。</p></header>
      <div className="control-row"><div><h3>强调色</h3><p>只调整导航焦点与关键动作，不改变风险状态颜色。</p></div><div className="control-palette" role="group" aria-label="强调色">
        {accentOptions.map(option => <button type="button" key={option.id} aria-pressed={preferences.accent === option.id} onClick={() => updatePreferences({ accent: option.id })}><span aria-hidden="true">{option.colors.map(color => <i key={color} style={{ background: color }} />)}</span>{option.label}{preferences.accent === option.id ? <Check size={14} aria-hidden="true" /> : null}</button>)}
      </div></div>
      <div className="control-row"><div><h3>信息密度</h3><p>紧凑模式减少系统页的垂直间距。</p></div><div className="control-segment" role="group" aria-label="信息密度"><button type="button" aria-pressed={preferences.density === "comfortable"} onClick={() => updatePreferences({ density: "comfortable" })}>舒适</button><button type="button" aria-pressed={preferences.density === "compact"} onClick={() => updatePreferences({ density: "compact" })}>紧凑</button></div></div>
      <div className="control-row"><div><h3>减少动画</h3><p>关闭装饰动画与非必要过渡。</p></div><label className="control-checkbox"><input aria-label="减少动画" type="checkbox" checked={preferences.reduceMotion} onChange={event => updatePreferences({ reduceMotion: event.target.checked })} />启用</label></div>
    </section>

    <section id="runtime" className="control-section" aria-labelledby="runtime-title">
      <header><h2 id="runtime-title">本机服务与账户</h2><p>本地 API 可用不代表已连接真实工厂。</p></header>
      <dl className="control-facts"><div><dt>前端</dt><dd>{platform.runtime === "TAURI" ? "Windows 桌面工作台" : "浏览器工作台"}</dd></div><div><dt>本地 API</dt><dd>{connection.api === "CONNECTED" ? "已连接" : connection.api === "CHECKING" ? "正在检查" : "未连接"}</dd></div><div><dt>当前账户</dt><dd>{account.user ? account.user.display_name : "未登录"}</dd></div>{account.user ? <><div><dt>用户 ID</dt><dd><code>{account.user.user_id}</code></dd></div><div><dt>本地权限</dt><dd>{account.user.platform_role === "ADMIN" ? "平台管理员" : "项目成员"} · {account.user.status}</dd></div></> : null}</dl>
      <div className="control-inline-links"><Link to="/account">{account.user ? "管理账户与会话" : "登录本地账户"}</Link><span>企业 SSO / MFA：未验证</span></div>
    </section>

    <section id="providers" className="control-section" aria-labelledby="providers-title"><header><h2 id="providers-title">模型与 API</h2><p>在统一入口管理 Agent 语言模型、本机 Ollama 和视觉训练模型。</p></header><div className="control-row"><div><h3>模型连接与训练</h3><p>连接测试、密钥保存和训练授权分别确认；此页不会自动测试模型。</p></div><Link className="control-link-action" to="/models">管理模型与 API</Link></div></section>

    <section id="data" className="control-section" aria-labelledby="data-title"><header><h2 id="data-title">隐私边界</h2></header><ul className="control-notes"><li>原图默认留在本地；这是系统策略，不是当前会话的外发流量统计。</li><li>浏览器不持久化模型 Key。保存的凭证由本机服务管理，页面不回显秘密值。</li><li>项目与公开回放隔离；API 失败时不使用样例替代用户数据。</li></ul><Link to="/integrations">管理数据来源与授权</Link></section>

    <section id="desktop" className="control-section" aria-labelledby="desktop-title"><header><h2 id="desktop-title"><Monitor size={17} aria-hidden="true" /> Windows 桌面</h2><p>{platform.runtime === "TAURI" ? "当前运行在桌面容器中；安装版本、签名与干净机验收仍需各自证据。" : "当前为浏览器运行。无法据此判断你是否已安装桌面版本。"}</p></header>
      {runtimeLoading ? <p role="status">正在读取本机配置路径…</p> : null}
      {runtimeError ? <div className="control-feedback is-error" role="alert"><p>{runtimeError}</p><button type="button" onClick={() => setRuntimeAttempt(value => value + 1)}>重新读取桌面配置</button></div> : null}
      {desktopRuntime ? <><dl className="control-facts"><div><dt>本地数据目录</dt><dd><code>{desktopRuntime.dataRoot}</code></dd></div><div><dt>配置文件</dt><dd><code>{desktopRuntime.configFile}</code></dd></div></dl><button type="button" className="control-button" disabled={opening} onClick={() => void openDirectory()}>{opening ? <LoaderCircle size={15} className="is-spinning" /> : <FolderOpen size={15} />}{opening ? "正在打开…" : "打开配置目录"}</button></> : null}
      {directoryMessage ? <p className={`control-feedback${directoryMessage.failed ? " is-error" : ""}`} role={directoryMessage.failed ? "alert" : "status"}>{directoryMessage.text}</p> : null}
    </section>
  </div>;
}
