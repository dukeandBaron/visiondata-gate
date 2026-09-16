# 项目 Skill 规范

这里有 5 份版本化的**文本工作流规范**，索引见 [manifest.json](manifest.json)。它们描述角色、输入、输出和失败边界；不是通用于所有 Agent 框架的一键插件包。

| Skill 规范 | 主要输入 | 输出与权限边界 |
| --- | --- | --- |
| [contract-intake](contract-intake/SKILL.md) | 目标、批次清单与合同 | 已校验上下文或明确拒绝原因 |
| [parallel-evidence-audit](parallel-evidence-audit/SKILL.md) | 合同、工具白名单与预算 | ToolTrace、Finding 和量测证据 |
| [evidence-grounded-council](evidence-grounded-council/SKILL.md) | 证据、受控知识与工具记录 | 有引用的辅助解释，不取得裁决权 |
| [fail-closed-policy](fail-closed-policy/SKILL.md) | 类型化发现、执行记录与冻结规则 | 唯一数据门禁决定；缺证据不默认通过 |
| [reserve-repair-recheck](reserve-repair-recheck/SKILL.md) | 工单、保留副本和原合同 | 派生版本与独立复验，原始输入保持不变 |

## 文本规范与可执行 SDK

- 可以阅读、复制并按项目许可证改编这些文本，用作受控流程的设计输入。
- 把 `SKILL.md` 放进一个目录，不等于已经安装、注册、授权、调度或验证其工具。
- 当前目录不承诺是 Codex、Claude Code、MCP 或其他框架的通用插件格式，也不证明 Hosted AgentTeams 已接入。
- 运行工业测量插件应使用 [Industrial Skill SDK](../docs/INDUSTRIAL_SKILL_SDK.md) 的显式注册机制。内置 `MetadataCountDriftSkill` 是确定性实现，不是把 Markdown 当 Python 执行。

索引格式为 `visiondata-gate.skill-manifest.v1`，当前 5 份规范版本为 `1.0.0`；它们独立于软件包的 `0.1.0`。改变输入、输出、失败或权限语义时应升级相应版本并记录兼容影响。

[可执行示例](../examples/reuse/README.md) · [版本策略](../docs/VERSIONING.md) · [许可证](../docs/LICENSING.md)
