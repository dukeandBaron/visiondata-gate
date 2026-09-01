# 受控真实模型 Planner

## 当前边界

工业案件闭环可选接入一个 OpenAI-compatible
`EvidenceGapPlanner / CounterevidencePlanner`。默认模式为 `off`，因此仅把 URL
写入配置并不代表真实后端已经连接。

模型只允许：

- 在当前案件已经触发的白名单 Worker 中给出优先级；
- 引用已有 Receipt ID 和冻结的缺失证据 ID；
- 提出竞争假设与反证问题；
- 生成咨询性、可校验的 Planner Receipt；未配置签名时不称为数字签名回执。

模型不能：

- 创造 Receipt、工具结果或生产事实；
- 删除尚未检查的证据分支；
- 修改 Frozen Policy Judge；
- 确立根因、批准 CAPA 或宣布生产恢复；
- 写 PLC、调用设备方法或控制相机、光源、IO、配方。

实际控制链为：

```text
LLM proposes
→ JSON Schema validation
→ hypothesis / evidence / Receipt ID validation
→ active Worker allowlist validation
→ reason-code and budget validation
→ gated/replay mode may prioritize eligible Workers
→ deterministic Workers observe
→ Frozen Policy Judge determines case state
→ named quality owner authorizes the next action
```

自由文本建议只保存在标记为 advisory 的 Planner Receipt 中，不进入 Judge
事实表。调度边界只接收验证后的 Worker Role 和 Reason Code。

## 治理记忆进入计划前，而不是事后附件

当案件选择 `approved_site` 记忆档案时，主链先按 Site Pack 和当前 Line 作用域
检索，再构造不可变 Case：

```text
request + Gate context + resume lineage
→ planning_subject_sha256
→ site/line scoped approved-memory retrieval
→ GovernedMemoryPlanningInput
→ optional Planner / deterministic Worker scheduling
→ immutable Case
→ final advisor context and runtime profile binding
```

检索只执行一次。`model_planner_receipt`、Case、`governed_context.json` 和
`profile_binding.json` 共同封印同一个 `memory_retrieval_receipt_sha256`。被拒绝的
跨 Site、跨 Line、过期、撤销、不相关或超出 Top-K 的候选仍完整保留在 Retrieval
Receipt 中，但其内容不会进入 Planner 可见上下文。

Planner 只看到 accepted historical references，并且只能用它们调整缺失证据顺序、
提出反证问题或给已经激活的白名单 Worker 排优先级。治理记忆的
`current_case_fact_authority`、`root_cause_authority` 和 `decision_authority` 均固定为
`none`；Frozen Policy Judge 不读取历史记忆作为当前事实。

## 四种模式

| 模式 | 外部请求 | 是否影响 Worker 优先级 | 用途 |
|---|---:|---:|---|
| `off` | 否 | 否 | 默认确定性版本 |
| `shadow` | 是 | 否 | 收集真实模型质量证据 |
| `gated` | 是 | 仅验证通过后 | 受控动态规划 |
| `replay` | 否 | 仅验证通过后 | CI、评委复现和冻结演示 |

模型请求失败、返回非 JSON、引用不存在的证据、推荐非活动 Worker、Reason Code
不匹配或超预算时，整份计划拒绝，并回退到确定性顺序。Frozen Judge 不读取失败
输出，因此 API 故障不能制造错误 PASS。

## 配置

仓库中的 `.env.example` 只含占位符；应用不会自动读取 `.env` 文件。请在本地
进程环境中设置值，不要把真实 Key 写入仓库、命令历史、截图、UI 或证据包。

DeepSeek OpenAI 兼容 Base URL、运行时完整端点与模型：

```text
Base URL: https://api.deepseek.com
Endpoint: https://api.deepseek.com/chat/completions
deepseek-v4-flash-vision-exp
```

PowerShell 的影子模式示例：

```powershell
$env:VISIONDATA_INCIDENT_MODEL_MODE = "shadow"
$env:VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE = "true"
$env:VISIONDATA_INCIDENT_MODEL_BASE_URL = "https://api.deepseek.com"
$env:VISIONDATA_INCIDENT_MODEL_ENDPOINT = "" # 可选完整 Endpoint；非空时优先
$env:VISIONDATA_INCIDENT_MODEL_NAME = "deepseek-v4-flash-vision-exp"
$env:VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS = "api.deepseek.com"
$env:VISIONDATA_INCIDENT_MODEL_API_KEY = "YOUR_API_KEY"
```

`VISIONDATA_INCIDENT_MODEL_BASE_URL` 会安全归一化到 Chat Completions 路径：网关根
路径补 `/v1/chat/completions`，以 `/v1` 结尾时只补 `/chat/completions`。归一化后
仍必须通过 HTTPS 与 `VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS` 检查。空的 Endpoint
和 Model Name 不会形成空配置：它们分别回退到冻结默认 Endpoint 与默认 Model；
这只是零网络配置解析，不代表真实后端已连接。

设置环境变量本身不会发起请求。创建一个新的工业案件版本时才调用一次 Planner，
例如：

```powershell
visiondata-gate incident-evaluate `
  --request incident-request.json `
  --gate-context gate-context.json `
  --output incident-case.json
```

命令摘要会输出 `model_planner_mode`、`model_connection_status` 和
`external_model_call_count`；完整验证结果位于案件 JSON 的
`model_planner_receipt`。

先使用 `shadow` 形成真实成功/失败回执。只有 Schema、引用、权限、预算和失败路径
评测通过后，才把模式切换为：

```powershell
$env:VISIONDATA_INCIDENT_MODEL_MODE = "gated"
```

切换只对新建的案件版本生效；历史案件不可变。

## Replay

`replay` 读取一份直接的 Planner JSON 对象，不读取 Chat Completions 外层包装，也
不需要 API Key：

```powershell
$env:VISIONDATA_INCIDENT_MODEL_MODE = "replay"
$env:VISIONDATA_INCIDENT_MODEL_REPLAY_PATH = "D:\absolute\path\planner-response.json"
```

示例文件是
`examples/incident_model_replay.fixture.json`。Replay 是案件合同绑定的；如果其中
的假设、证据、Worker 或 Reason Code 不属于当前案件，它会按设计被拒绝。

## 回执与声明

成功案件会带有 `model_planner_receipt`，其中记录：

- secret-free 配置摘要和 Planner 输入摘要；
- 治理记忆 Planning Input 摘要与 Retrieval Receipt 摘要（如启用）；
- HTTP 请求/响应摘要与重试状态；
- Schema、证据、Worker、Reason Code、预算和权限检查结果；
- 推荐顺序与实际应用顺序；
- `model_call_count`、P50/P95 可用的 HTTP 时延基础回执、Token 使用量、连接边界和模型身份强度。

若服务返回 OpenAI-compatible `usage`，系统记录 input/output/total token；由于当前
没有冻结供应商计价表，费用状态明确为
`TOKENS_REPORTED_COST_NOT_COMPUTED`，不会臆造金额。

回执不保留 API Key、Authorization Header、原始图片或无效原始模型输出。

在填入 Key 并产生远程 `SUCCESS` 回执前，正确状态始终是：

```text
REAL_BACKEND_NOT_CONNECTED
```

即使远程响应成功，`response_only` 也只证明端点返回了配置的模型名称，不证明
具体 checkpoint 权重或生产部署。启用远程模式会向第三方服务发送经过裁剪的
案件问题、假设和标识符；真实企业案件必须先取得数据外发授权。原始图像不会由
该 Planner 发送。
