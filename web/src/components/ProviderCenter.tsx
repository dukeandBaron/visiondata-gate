import {
  Cable,
  CheckCircle2,
  CloudCog,
  KeyRound,
  LoaderCircle,
  ShieldCheck,
  Star,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import type {
  ProviderConnectionTestResult,
  ProviderKind,
  ProviderProfileInput,
  ProviderProfileRecord,
} from "../domain";
import {
  createProviderProfile,
  listProviderProfiles,
  revokeProviderProfile,
  setDefaultProviderProfile,
  testProviderConnection,
  testSavedProviderConnection,
} from "../data/api";
import { useProduct } from "../ProductContext";
import { ClaimBoundary, Panel, PanelHeader, StatusBadge } from "./ui";

const providerDefaults: Record<
  ProviderKind,
  { label: string; baseUrl: string; model: string; keyRequired: boolean }
> = {
  deepseek: {
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-chat",
    keyRequired: true,
  },
  openai: {
    label: "OpenAI",
    baseUrl: "https://api.openai.com",
    model: "gpt-4.1-mini",
    keyRequired: true,
  },
  opentoken: {
    label: "OpenToken",
    baseUrl: "https://gw.opentoken.io",
    model: "",
    keyRequired: true,
  },
  openai_compatible: {
    label: "企业 OpenAI-compatible",
    baseUrl: "",
    model: "",
    keyRequired: true,
  },
  ollama_local: {
    label: "Ollama（本机）",
    baseUrl: "http://127.0.0.1:11434",
    model: "qwen3:8b",
    keyRequired: false,
  },
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "模型配置操作失败。";
}

function statusTone(
  status: ProviderProfileRecord["last_test_status"] | ProviderConnectionTestResult["status"],
) {
  if (status === "CONNECTED") return "success" as const;
  if (status === "NOT_TESTED") return "neutral" as const;
  return "warning" as const;
}

export function ProviderCenter() {
  const { activeWorkspace, connection } = useProduct();
  const [providerKind, setProviderKind] = useState<ProviderKind>("deepseek");
  const [displayName, setDisplayName] = useState("我的 DeepSeek");
  const [baseUrl, setBaseUrl] = useState(providerDefaults.deepseek.baseUrl);
  const [model, setModel] = useState(providerDefaults.deepseek.model);
  const [apiKey, setApiKey] = useState("");
  const [plannerMode, setPlannerMode] = useState<"shadow" | "gated">("shadow");
  const [profiles, setProfiles] = useState<ProviderProfileRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mutatingId, setMutatingId] = useState("");
  const [feedback, setFeedback] = useState<string>();
  const [error, setError] = useState<string>();
  const [testResult, setTestResult] = useState<ProviderConnectionTestResult>();

  const reload = useCallback(async () => {
    if (!activeWorkspace || connection.api !== "CONNECTED") {
      setProfiles([]);
      return;
    }
    setLoading(true);
    try {
      setProfiles(await listProviderProfiles(activeWorkspace.workspace_id));
    } catch (caught) {
      setError(messageOf(caught));
      setProfiles([]);
    } finally {
      setLoading(false);
    }
  }, [activeWorkspace?.workspace_id, connection.api]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const chooseProvider = (kind: ProviderKind) => {
    const defaults = providerDefaults[kind];
    setProviderKind(kind);
    setDisplayName(`我的 ${defaults.label}`);
    setBaseUrl(defaults.baseUrl);
    setModel(defaults.model);
    setApiKey("");
    setTestResult(undefined);
    setFeedback(undefined);
    setError(undefined);
  };

  const draft = (): ProviderProfileInput => {
    if (!activeWorkspace) throw new Error("请先选择工作区。");
    return {
      workspaceId: activeWorkspace.workspace_id,
      displayName,
      providerKind,
      baseUrl,
      model,
      apiKey,
      defaultPlannerMode: plannerMode,
      makeDefault: true,
    };
  };

  const runDraftTest = async (): Promise<ProviderConnectionTestResult> => {
    const input = draft();
    if (providerDefaults[providerKind].keyRequired && !apiKey.trim()) {
      throw new Error("请输入 API Key；Key 只会发送到本机服务端。 ");
    }
    const result = await testProviderConnection(input);
    setTestResult(result);
    if (result.status !== "CONNECTED") {
      throw new Error(`连接未通过：${result.reason_code}`);
    }
    return result;
  };

  const testDraft = async () => {
    setSaving(true);
    setError(undefined);
    setFeedback(undefined);
    try {
      const result = await runDraftTest();
      setFeedback(`连接成功 · ${Math.round(result.latency_ms)} ms · ${result.model}`);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(undefined);
    setFeedback(undefined);
    try {
      await runDraftTest();
      const saved = await createProviderProfile(draft());
      setApiKey("");
      setTestResult(undefined);
      setFeedback(`${saved.display_name} 已保存为当前用户在本工作区的默认模型。`);
      await reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  };

  const operate = async (
    profile: ProviderProfileRecord,
    action: "test" | "default" | "revoke",
  ) => {
    if (
      action === "revoke" &&
      !window.confirm(`撤销“${profile.display_name}”并删除其本机加密凭证？`)
    ) {
      return;
    }
    setMutatingId(profile.profile_id);
    setError(undefined);
    setFeedback(undefined);
    try {
      if (action === "test") {
        const result = await testSavedProviderConnection(profile.profile_id);
        setFeedback(
          result.status === "CONNECTED"
            ? `${profile.display_name} 连接成功 · ${Math.round(result.latency_ms)} ms`
            : `${profile.display_name} 连接未通过 · ${result.reason_code}`,
        );
      } else if (action === "default") {
        await setDefaultProviderProfile(profile.profile_id);
        setFeedback(`${profile.display_name} 已设为当前工作区默认模型。`);
      } else {
        await revokeProviderProfile(profile.profile_id);
        setFeedback(`${profile.display_name} 已撤销，本机加密凭证已删除。`);
      }
      await reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setMutatingId("");
    }
  };

  return (
    <section id="providers" className="settings-section provider-center">
      <header>
        <span><CloudCog size={15} /> MODEL PROVIDERS / BYOK</span>
        <h2>模型接入中心</h2>
        <p>客户在这里填写自己的 DeepSeek、OpenToken、OpenAI 或企业兼容模型。</p>
      </header>

      {!activeWorkspace ? (
        <ClaimBoundary title="尚未选择工作区" tone="warning">
          先在顶部工作区选择器中选择工作区，再创建当前用户私有的模型配置。
        </ClaimBoundary>
      ) : null}

      <div className="provider-center__grid">
        <Panel variant="raised">
          <PanelHeader
            eyebrow="ADD PROVIDER"
            title="输入客户模型凭证"
            detail="测试成功后才保存；API Key 使用 DPAPI 加密并绑定当前 Windows 用户。"
          />
          <form className="provider-form" onSubmit={(event) => void save(event)}>
            <label>
              <span>Provider</span>
              <select
                value={providerKind}
                onChange={(event) => chooseProvider(event.target.value as ProviderKind)}
                disabled={saving}
              >
                {Object.entries(providerDefaults).map(([id, item]) => (
                  <option key={id} value={id}>{item.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>配置名称</span>
              <input
                required
                minLength={2}
                maxLength={100}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="provider-form__wide">
              <span>Base URL</span>
              <input
                required
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                disabled={saving || providerKind !== "openai_compatible"}
                spellCheck={false}
              />
              <small>预置 Provider 锁定官方 Host；企业兼容模式必须使用 HTTPS。</small>
            </label>
            <label>
              <span>模型 ID</span>
              <input
                required
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="例如 deepseek-chat"
                disabled={saving}
                spellCheck={false}
              />
            </label>
            <label>
              <span>默认运行模式</span>
              <select
                value={plannerMode}
                onChange={(event) => setPlannerMode(event.target.value as "shadow" | "gated")}
                disabled={saving}
              >
                <option value="shadow">Shadow · 只观察不改编排</option>
                <option value="gated">Gated · 仅在合同内参与规划</option>
              </select>
            </label>
            <label className="provider-form__wide">
              <span>API Key</span>
              <div className="provider-key-field">
                <KeyRound size={16} />
                <input
                  required={providerDefaults[providerKind].keyRequired}
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={providerDefaults[providerKind].keyRequired ? "输入客户自己的 API Key" : "本机 Ollama 无需 Key"}
                  autoComplete="off"
                  data-1p-ignore
                  data-lpignore="true"
                  spellCheck={false}
                  disabled={saving}
                />
              </div>
              <small>不会写入 localStorage、sessionStorage、普通 SQLite、日志或回执；保存后输入框立即清空。</small>
            </label>

            {testResult ? (
              <div className="provider-test-result">
                <StatusBadge tone={statusTone(testResult.status)}>{testResult.status}</StatusBadge>
                <span>{testResult.endpoint_host}</span>
                <code>{testResult.reason_code}</code>
              </div>
            ) : null}
            {feedback ? <p className="provider-feedback is-success"><CheckCircle2 size={14} /> {feedback}</p> : null}
            {error ? <p className="provider-feedback is-error">{error}</p> : null}

            <div className="provider-form__actions">
              <button
                type="button"
                onClick={() => void testDraft()}
                disabled={!activeWorkspace || connection.api !== "CONNECTED" || saving}
              >
                {saving ? <LoaderCircle className="is-spinning" size={14} /> : <Cable size={14} />}
                测试连接
              </button>
              <button
                className="is-primary"
                type="submit"
                disabled={!activeWorkspace || connection.api !== "CONNECTED" || saving}
              >
                {saving ? <LoaderCircle className="is-spinning" size={14} /> : <ShieldCheck size={14} />}
                测试并安全保存
              </button>
            </div>
          </form>
        </Panel>

        <Panel>
          <PanelHeader
            eyebrow="MY PROVIDERS"
            title="当前用户的模型配置"
            detail={`${activeWorkspace?.name ?? "未选择工作区"} · 不与其他用户共享 Key`}
          />
          <div className="provider-profile-list">
            {loading ? <p className="provider-profile-empty"><LoaderCircle className="is-spinning" size={15} /> 正在读取配置…</p> : null}
            {!loading && profiles.length === 0 ? (
              <p className="provider-profile-empty">当前用户在此工作区还没有模型配置。</p>
            ) : null}
            {profiles.map((item) => (
              <article key={item.profile_id}>
                <div className="provider-profile-list__head">
                  <span><CloudCog size={17} /></span>
                  <div>
                    <strong>{item.display_name}</strong>
                    <small>{providerDefaults[item.provider_kind].label} · {item.model}</small>
                  </div>
                  {item.is_default ? <StatusBadge tone="success">DEFAULT</StatusBadge> : null}
                </div>
                <div className="provider-profile-list__facts">
                  <span>host <strong>{item.endpoint_host}</strong></span>
                  <span>secret <strong>{item.secret_configured ? "DPAPI" : "NONE"}</strong></span>
                  <span>mode <strong>{item.default_planner_mode.toUpperCase()}</strong></span>
                  <span>test <StatusBadge tone={statusTone(item.last_test_status)}>{item.last_test_status}</StatusBadge></span>
                </div>
                <code>{item.config_sha256.slice(0, 16)}…</code>
                <footer>
                  <button type="button" onClick={() => void operate(item, "test")} disabled={Boolean(mutatingId)}>
                    {mutatingId === item.profile_id ? <LoaderCircle className="is-spinning" size={13} /> : <Cable size={13} />} 测试
                  </button>
                  {!item.is_default ? (
                    <button type="button" onClick={() => void operate(item, "default")} disabled={Boolean(mutatingId)}><Star size={13} /> 设为默认</button>
                  ) : null}
                  <button className="is-danger" type="button" onClick={() => void operate(item, "revoke")} disabled={Boolean(mutatingId)}><Trash2 size={13} /> 撤销</button>
                </footer>
              </article>
            ))}
          </div>
        </Panel>
      </div>

      <ClaimBoundary title="BYOK 当前安全边界" tone="warning">
        Provider Profile 已按用户和工作区隔离，但当前 Actor Header 仍是本机原型身份，不是公网登录认证。凭证管理默认只允许本机回环访问；部署到多人服务器前必须接入真实 IAM 与 TLS。
      </ClaimBoundary>
    </section>
  );
}
