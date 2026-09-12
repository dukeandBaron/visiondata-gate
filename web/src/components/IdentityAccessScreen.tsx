import { ArrowRight, Fingerprint, KeyRound, LoaderCircle, LockKeyhole, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useIdentity } from "../IdentityContext";

export function IdentityAccessScreen() {
  const identity = useIdentity();
  const [registering, setRegistering] = useState(false);
  const [loginName, setLoginName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [validation, setValidation] = useState<string>();
  const settingUp = identity.status === "setup";
  const creating = settingUp || registering;

  useEffect(() => {
    setPassword(""); setConfirmation(""); setValidation(undefined);
    if (identity.notice) setRegistering(false);
  }, [identity.status, identity.notice]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setValidation(undefined);
    if (identity.busy) return;
    if (creating && password !== confirmation) { setValidation("两次输入的密码不一致。"); return; }
    const rawPassword = password;
    setPassword(""); setConfirmation("");
    if (settingUp) await identity.setup({ login_name: loginName.trim().toLowerCase(), display_name: displayName.trim(), password: rawPassword });
    else if (registering) await identity.register({ login_name: loginName.trim().toLowerCase(), display_name: displayName.trim(), password: rawPassword });
    else await identity.login({ login_name: loginName.trim().toLowerCase(), password: rawPassword });
  };

  return <main className="identity-access" data-testid="identity-access-screen">
    <header className="identity-access__topbar"><span className="identity-brand"><ShieldCheck size={21} /> VisionData Gate</span><span>私域工作台 · 本地账户</span></header>
    <div className="identity-access__body">
      <aside className="identity-access__context">
        <span className="identity-eyebrow">IDENTITY BEFORE ACTION</span>
        <h1>每一次操作，<br />都有明确的身份。</h1>
        <p>使用本地账户进入工作区。数据、模型和任务保持各自的访问范围，登录不会自动获得已有项目的权限。</p>
        <div className="identity-boundary-map" aria-label="访问权限边界">
          <div><span><KeyRound size={17} /></span><section><strong>本机连接</strong><small>启动入口提供实例访问凭证</small></section></div>
          <div className="identity-boundary-map__active"><span><Fingerprint size={17} /></span><section><strong>用户登录</strong><small>密码校验后建立独立用户会话</small></section><span className="identity-step-dot" /></div>
          <div><span><LockKeyhole size={17} /></span><section><strong>工作区授权</strong><small>由已有成员与所有者权限决定</small></section></div>
        </div>
        <small className="identity-access__boundary">本地密码认证，不是企业 SSO。人工审批与生产放行仍需当次确认。</small>
      </aside>
      <section className="identity-access__form-panel" aria-label="身份访问">
        {identity.status === "loading" ? <div className="identity-wait" role="status"><LoaderCircle size={24} /><h2>正在核对身份服务</h2><p>确认本机服务状态后才显示登录入口。</p></div>
          : identity.status === "error" ? <div className="identity-wait"><ShieldCheck size={28} /><h2>暂时无法确认账户状态</h2><p role="alert">{identity.error}</p><button className="identity-button identity-button--primary" onClick={() => void identity.refresh()}><RefreshCw size={16} /> 重新检查状态</button><small>不会自动重复初始化、注册或登录。</small></div>
            : <>
              <span className="identity-eyebrow">{settingUp ? "FIRST ADMINISTRATOR" : registering ? "REQUEST ACCESS" : "LOCAL ACCOUNT"}</span>
              <h2>{settingUp ? "创建首个管理员" : registering ? "申请加入工作台" : "登录工作台"}</h2>
              <p className="identity-form-intro">{settingUp ? "为当前本机主体设置登录凭证。已有工作区与数据保持原有归属。" : registering ? "申请由管理员审批。通过后，仍需工作区所有者单独授予成员权限。" : "令牌仅留在本页内存，刷新或关闭页面后需要重新登录。"}</p>
              <form className="identity-form" onSubmit={(event) => void submit(event)}>
                <label htmlFor="identity-login-name">登录名<input id="identity-login-name" aria-label="登录名" aria-describedby="identity-login-hint" name="username" autoComplete="username" required minLength={3} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,63}" value={loginName} onChange={(event) => setLoginName(event.target.value)} disabled={identity.busy} spellCheck={false} autoCapitalize="none" /><small id="identity-login-hint">3–64 位英文字母、数字、点、下划线或连字符，不区分大小写。</small></label>
                {creating ? <label htmlFor="identity-display-name">显示名称<input id="identity-display-name" name="display_name" required maxLength={120} autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={identity.busy} /></label> : null}
                <label htmlFor="identity-password">密码<input id="identity-password" aria-label="密码" aria-describedby={creating ? "identity-password-hint" : undefined} name="password" type="password" autoComplete={creating ? "new-password" : "current-password"} required minLength={12} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} disabled={identity.busy} />{creating ? <small id="identity-password-hint">12–256 个字符；保留输入中的空格，不自动裁剪。</small> : null}</label>
                {creating ? <label htmlFor="identity-password-confirmation">再次输入密码<input id="identity-password-confirmation" name="password_confirmation" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={identity.busy} /></label> : null}
                {validation || identity.error ? <p className="identity-feedback identity-feedback--error" role="alert">{validation || identity.error}</p> : null}
                {identity.notice ? <p className="identity-feedback" role="status">{identity.notice}</p> : null}
                <button className="identity-button identity-button--primary" type="submit" disabled={identity.busy}>{identity.busy ? <LoaderCircle size={16} /> : <ArrowRight size={16} />}{identity.busy ? "正在确认…" : settingUp ? "创建管理员并登录" : registering ? "提交注册申请" : "登录"}</button>
              </form>
              {!settingUp ? <button className="identity-text-button" disabled={identity.busy} onClick={() => { setRegistering((value) => !value); setPassword(""); setConfirmation(""); setValidation(undefined); }}>{registering ? "已有账户？返回登录" : "没有账户？提交注册申请"}</button> : <p className="identity-form-footnote">初始化只执行一次。结果不明确时先检查状态，不会自动重试。</p>}
            </>}
      </section>
    </div>
    <footer className="identity-access__footer"><span>LOCAL IDENTITY · WORKSPACE SCOPED</span><span>无云端注册 · 无密码回显 · 无自动授权</span></footer>
  </main>;
}
