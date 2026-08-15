# 决策日志

## 2026-08-09

- 选择工业视觉数据发布门禁，不选择材料研发或工业计量验收：程序化缺陷可形成隐藏真值，纯 AI 闭环更可证伪。
- 图像为主模态；点云仅作为后续扫描数据就绪插件。
- 复用 ProcessPilot 的类型化计划、白名单工具、Trace、确定性构包与 QA 思路，不复制许可证边界不明的算法实现。
- 公开数据只提供来源与下载说明，不随作品包再分发；主 Demo 使用自生成工业风格图像。
- 不把 AI 角色包装为真人专家，不把多个同源 Agent 投票当独立证据。

## 2026-08-12

- `1111.docx` 按用户确认作为头脑风暴会录音转写完整审阅；回放没有画面，不再写“内容未看”，但不得声称核验视觉内容。
- 依据录音转写 P562-P574 与赛道分享 FAQ，`mapped_not_connected` 是 AgentTeams 硬风险，不能只用协议命名遮蔽。
- 官方 AgentTeams 对齐版本固定为 v1.2.2、commit `aa650ccacc2ba6171d1b0b5efd2a49b1472abe5d`、API `agentteams.io/v1beta1`。
- 增加 Worker/Team 资源、`Worker.spec.skills` 分发计划和真实 Matrix receipt 哈希门禁；静态 PASS 永不自动升级为 connected。
- 增加 `claim_scope_receipt.json`，将真实客户、真实工业数据、生产部署、官网回执、真人专家和回放视觉内容列为禁止外推项。
