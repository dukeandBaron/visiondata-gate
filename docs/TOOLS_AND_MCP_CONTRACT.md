# 工具契约与 MCP 迁移边界

当前运行时使用本地 `Tool Gateway`，不是把网络接口冒充成 MCP 连接。每个工具都在
allowlist 中注册，返回 typed `ToolTrace`、finding IDs、输入/结果摘要哈希和错误状态。
后续若接入 MCP/远程 AgentTeams，只替换 adapter，不改变 Policy Judge 的输入契约。

## 等价工具契约

| 字段 | 本地契约 | MCP/远程迁移要求 |
|---|---|---|
| `name` | `image_quality`、`duplicate_leakage`、`annotation_integrity`、`coverage_matrix`、`governance_audit` | 服务名与版本必须锁定，禁止运行时任意发现工具 |
| `input` | 相对路径 `BatchManifest` + `BatchContract`；禁止绝对路径/越权 | JSON Schema 与版本号固定；服务端再次校验 |
| `output` | `Finding[]`、metrics、`ToolTrace` | 保持同字段；未知字段拒绝或显式降级 |
| `auth` | 本地进程权限 + allowlist | mTLS/OAuth/网关授权；凭据不下发 Worker |
| `error` | `ok` / `error` / `skipped`；缺失证据 fail-closed | 网络超时、鉴权失败、schema 错误均映射为 typed error |
| `retry` | 运行时受 `max_retries` 限制 | 必须声明幂等键；禁止无界重试或重复副作用 |
| `audit` | 输入/结果摘要哈希、序号、finding refs | 保留 trace id、调用者身份、策略版本和服务端 digest |
| `side_effect` | 测量工具只读；repair 只操作 reserve 副本 | L0/L1/L2/L3 分级；生产动作必须外部授权 |
| `migration_cost` | 无网络依赖，离线可复现 | 需实现 transport adapter、凭据注入、超时/重试、服务健康检查和回放 fixture |

## 迁移验收门

远程接入不能以“接口能返回 JSON”作为完成标准，至少应同时提供：

- 同一输入在 local 与 remote adapter 上的 canonical result digest 对照；
- tool lock（名称、版本、schema digest、权限范围）；
- timeout、重复调用、重排/去重、提示注入和权限缺失场景；
- 服务不可用时的 `DEFER` 回执；
- 不含密钥和原始敏感载荷的可回放 trace。

## 上下文传递验收

工具迁移前还必须保留运行时的 `ContextTransfer` 语义：每个源任务到目标任务的
依赖边都要有稳定 payload digest、输入/输出引用和失败状态。远程工具返回错误、
超时或权限不足时，相关边必须进入 `deferred`/`rejected`，并由 Policy Judge
继续 fail-closed；不能因为 transport 返回了 JSON 就把上下文标成 accepted。

在这些条件未满足前，`connection_status=mapped_not_connected` 和
`matrix_connected=false` 必须保持不变。
