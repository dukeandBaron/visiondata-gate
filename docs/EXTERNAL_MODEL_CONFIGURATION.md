# 外部模型开发组配置｜OpenToken Gateway

VisionData Gate 可以把外部模型用于受控的 Evidence Gap Planner、反证建议或视觉证据建议，但外部模型没有门禁裁决权、CAPA 批准权、生产放行权或设备控制权。确定性工具、Frozen Policy Judge 与具名人工决定保持不变。

## 客户自己的模型从哪里输入

产品运行时的客户 BYOK 已有独立入口，不需要客户编辑仓库 `.env`：

1. 启动本机 API 与 Web 工作台；
2. 在顶部先选择工作区；
3. 打开 `设置 -> 模型接入`；
4. 选择 DeepSeek、OpenToken、OpenAI、企业 OpenAI-compatible 或本机 Ollama；
5. 填写配置名称、Base URL、模型 ID 和 API Key；
6. 点击“测试连接”，通过后点击“测试并安全保存”；
7. 进入 `案件 -> 导入工业事件`，在“本次案件使用的规划模型”中选择刚保存的配置。

远程 Provider 的 Key 只在密码输入与提交期间存在于 React 临时状态，不写入 `localStorage`、`sessionStorage`、普通 SQLite、日志、回执或案件 JSON。Windows 本机服务使用 DPAPI 保存密文；API 响应只返回 `secret_configured=true/false`，永不回显 Key。Incident v3 只绑定非秘密的 `provider_profile_id`，服务端再按当前 Actor 与 Task Workspace 双重核验后读取对应密钥。

这条能力当前的准确状态是 `LOCAL_BYOK_READY / PRODUCTION_AUTH_NOT_CONFIGURED`：Provider Profile 已按用户和工作区隔离，凭证管理路由默认只接受回环请求；但 `X-Actor-User-Id` 仍是本机原型身份头，不能宣称已经具备公网多租户认证。多人服务器部署前仍需接入真实 IAM、TLS、审计登录与密钥轮换。

下面的 `.env.local` 章节只服务于“开发 VisionData Gate UI 的外部模型工具”，不是客户在产品工作台里使用自己模型的入口。

## 安全默认配置

仓库的 [`.env.example`](../.env.example) 已预留：

```text
base_url=https://gw.opentoken.io
api_key=<由操作者在本机填写，仓库中保持空白>
builder_model=gemini-3.7-flash
allow_remote=false
```

仓库根目录已经创建 Git 忽略的 `.env.local`。产品 UI 与 API 启动脚本会自动读取它，Reviewer 冻结演示不会读取，从而避免评委页面进程接触真实 Key。

你只需要在本机编辑：

```text
<PROJECT_ROOT>\.env.local
```

OpenToken Key 只需写一次：

```text
VISIONDATA_OPENTOKEN_API_KEY=在等号后粘贴你的Key
```

该 Key 仅供外部 UI 开发工具使用，不会映射到产品 Incident Planner 或工业多模态 Advisor。仓库模板预设：

```text
VISIONDATA_UI_DEV_BUILDER_MODEL=gemini-3.7-flash
VISIONDATA_UI_DEV_VISUAL_REVIEW_MODEL=gemini-3.7-flash
VISIONDATA_UI_DEV_ALLOW_REMOTE=false
```

下面两个产品运行时 Key 保持空白，除非未来单独授权产品模型接入：

```text
VISIONDATA_INCIDENT_MODEL_API_KEY=
VISIONDATA_MULTIMODAL_ADVISOR_API_KEY=
```

即使旧配置中这两个字段已有值，启动器也会在以下硬门保持 `false` 时从产品进程中抑制它们：

```text
VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED=false
```

因此 UI 开发组可以使用 OpenToken，但不会顺带启用工业案件 Planner 或图像传输。

不要把 Key 发到聊天中。两个 `REPLACE_WITH_PROVIDER_MODEL_ID` 只属于尚未授权的产品运行时，必须继续保持 `MODE=off`。

UI 开发客户端在模型名以 `gemini-` 开头且显式 Endpoint 留空时，使用 Gemini 原生路径：

```text
https://gw.opentoken.io/v1beta/models/gemini-3.7-flash:generateContent
```

尚未启用的产品 Incident Planner 与多模态 Advisor 仍按 OpenAI-compatible 约定从 Base URL 派生：

```text
https://gw.opentoken.io/v1/chat/completions
```

这只是客户端路径推导，不证明网关一定采用该路径。启用前必须按服务商文档核对实际 Endpoint 和 Model ID；如路径不同，用 `VISIONDATA_INCIDENT_MODEL_ENDPOINT` 或 `VISIONDATA_MULTIMODAL_ADVISOR_ENDPOINT` 显式覆盖。

## 2026-08-27 实时调用结论

本机 `.env.local` 已确认 Key 非空、模型为 `gemini-3.7-flash`、UI 开发远程开关为 `true`；检查过程只输出 `SET_REDACTED`，未输出 Key 内容。产品运行时仍保持：

```text
VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED=false
VISIONDATA_INCIDENT_MODEL_MODE=off
VISIONDATA_MULTIMODAL_ADVISOR_ALLOW_IMAGE_TRANSMISSION=false
```

使用 `maxOutputTokens=256` 的最小文本请求分别探测：

| Gateway | HTTP | 服务端结果 |
|---|---:|---|
| `https://gw.opentoken.io` | 500 | `quota reservation failed: insufficient enterprise balance` |
| `https://cn2.gw.opentoken.io` | 500 | `quota reservation failed: insufficient enterprise balance` |

因此当前结论是：Key 已配置、请求已到达 Gateway，但 Gateway 没有为 Gemini 请求成功预留企业结算额度，`gemini-3.7-flash` 不能承担本轮 UI 开发。控制台中显示的 Key 月额度不能替代本次企业结算池的预留结果。当前状态应记为 `GATEWAY_QUOTA_RESERVATION_FAILED`，不能写成 `REAL_BACKEND_CONNECTED`；本轮 UI 由 SOL 继续实现。

2026-08-28 又使用不含业务数据的最小文本请求复查一次主网关和 `cn2` 网关；两者仍为 HTTP 500，错误仍是 `quota reservation failed: insufficient enterprise balance`。本次复查未产生模型输出、未传输图像，也没有启用产品 Incident Planner。因此当前状态不变。

## 安全启用顺序

1. 在本机进程环境中填写 Key，不要修改或提交 `.env.example`；
2. 填写服务商真实 Model ID；
3. 保持 `MODE=off`，先核对 endpoint、allowlist 和费用边界；
4. 先使用 `shadow`，模型输出只形成回执，不能改变 Worker 顺序；
5. 获得结构校验、身份与传输回执后，才考虑 `gated`；
6. 多模态图像传输需同时打开全局开关和逐图授权，默认保持关闭。

PowerShell 当前会话示例：

```powershell
$env:VISIONDATA_INCIDENT_MODEL_MODE = "shadow"
$env:VISIONDATA_INCIDENT_MODEL_BASE_URL = "https://gw.opentoken.io"
$env:VISIONDATA_INCIDENT_MODEL_NAME = "<provider-model-id>"
$env:VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS = "gw.opentoken.io"
$env:VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE = "true"
$env:VISIONDATA_INCIDENT_MODEL_API_KEY = "<fill-locally>"
```

不要把真实 Key 粘贴到文档、命令日志、截图、Issue、提交表单或 Reviewer Workbench。工作台只显示 `key_configured=true/false`，永不返回 Key 内容。

## 状态含义

| 状态 | 含义 |
|---|---|
| `NOT_CONFIGURED` | 模式关闭、Key 缺失或 endpoint 不完整；不会发起请求 |
| `CONFIGURED_NOT_PROBED` | 本机配置已齐，但尚无身份/传输回执 |
| `GATEWAY_QUOTA_RESERVATION_FAILED` | Key 已配置且 Gateway 返回响应，但服务端额度预留失败，没有产生模型输出 |
| `CONTRACT_CONNECTED_LOCAL_TEST` | 仅本地协议夹具通过，不是远端模型已连接 |
| `BACKEND_RESPONDED_IDENTITY_UNVERIFIED` | 远端有响应，但模型身份强度不足 |
| `REAL_BACKEND_CONNECTED` | 本次远端调用、身份与传输回执满足运行合同；仍不代表模型质量、客户验收或生产授权 |

外部模型的价格、可用模型名和服务条款均属于服务商实时状态，不能仅凭第三方截图写入当前工程事实。调用前由操作者确认预算、数据传输边界与服务条款。
