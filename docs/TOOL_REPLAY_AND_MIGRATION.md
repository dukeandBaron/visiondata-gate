# 工具回放与迁移验收

这是工业视觉数据治理应用的可信后台能力，不是部署承诺。每次本地运行会生成
`evidence/tool_replay_receipt.json`，对初始批次和复验批次中成功完成的工具重新执行同一
`BatchManifest + BatchContract`，比较：

- `input_sha256`：工具实际收到的输入与合同参数；
- `result_sha256`：Finding 与 metrics 的 canonical 结果；
- `finding_ids`：下游 Policy Judge 实际消费的稳定引用；
- `contract_digest`：权限、副作用、失败策略与 MCP 迁移目标的契约指纹。

回放失败或摘要不一致时，不能把远程/MCP 工具结果当作等价实现；适配器必须返回 typed
error/`DEFER`，而不是静默改变 Policy Judge 的输入。原始运行中的 skipped/error 工具不会
因为回放成功而被升级，原始 Judge 决策仍然有效。

当前回放是 `local-deterministic-replay`，证明的是同一代码、同一 fixture 的可重复性；它
不是 hosted AgentTeams/MCP 健康回执、供应商 SLA、客户验证或生产 SLO。

同一运行还生成 `evidence/tool_ablation_receipt.json`：逐工具移除其 typed
`ToolTrace` 与 finding 引用，再在同一合同下重算 Policy Judge，记录决策效果、丢失
finding、以及新增/解除的失败规则。该回执用于回答“这个工具删掉会失去哪条证据”，
并检查任何单工具移除都不会让门禁更宽松；它不是生产故障率、供应商 SLA 或远程
MCP 等价证明。
