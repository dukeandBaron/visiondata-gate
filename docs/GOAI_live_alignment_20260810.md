# 历史快照｜GOAI Agent Infra 赛道现场对齐记录（2026-08-10）

> **历史决策快照，已被后续赛道决策取代。** 本文保留用于说明方案如何演化，不是当前提交指南。当前唯一主口径为赛道二“无界应用 Boundless Agents”与 AI+工业制造，见 [`00_OVERVIEW.md`](00_OVERVIEW.md) 和 [`BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md`](BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md)；Agent Infra 仅作为可信后台能力。

核验时间：2026-08-10（北京时间）

## 当前可直接验证的赛事信息

- 官方 Agent Infra 赛道页：<https://www.goaihz.com/tracks?track=infra>
- 本轮读取返回 HTTP 200；页面正文明确要求企业级复杂任务下的多 Agent 基础设施与协同系统，设计不少于 3 个不同职能 Agent 的完整闭环，并关注 AgentTeams 编排、Skill 复用、工具集成、执行证据和安全审计。
- 初赛材料口径：方案 PPT、讲解视频、Skill 清单、Agent Identity 清单、工具/云产品清单；本项目已在源码包与证据页面中提供对应清单。
- 作品定位应是可运行、可验证、可复用的真实任务闭环；当前行业实例仍是 AI+工业制造的数据发布门禁。
- 本记录只确认本轮实际读取到的页面内容，不把页面存在等同于已经报名、上传或获得参赛资格。

## VisionData Gate 对齐结论

| 赛事关注点 | 已有实现 | 证据边界 |
|---|---|---|
| AI+工业制造 | 工业视觉数据进入实验训练池前的发布门禁 | 不判断零件合格或产线安全 |
| 任务闭环 | 合同→工具→AI 角色→策略→工单→reserve→同合同复验→交付 | reserve 是合成模拟，不是真实补采 |
| AgentTeams 协同 | Manager / Team Leader / Workers / Council / Judge / Operator 的 Team、Room、Task、Identity、Skill 映射 | 当前是 `local-deterministic` 契约映射，`mapped_not_connected`；不是 hosted Matrix 连接回执 |
| Skill 工程体系 | Contract Intake、Parallel Evidence Audit、Council Review、Fail-Closed Judge、Reserve Recheck 五类可复用 Skill | 输入/输出、依赖、失败模式和安全边界已进入映射快照 |
| 工具调用 | 质量、重复/泄漏、标注、覆盖四类白名单工具 | 数值只来自工具，不由角色补写 |
| 多模态 | 处理图像、mask、结构化 manifest 与报告 | 当前不含真实客户图像或视频输入 |
| 结果交付 | canonical JSON、CSV、离线 HTML、manifest、SHA-256 ZIP | 哈希只证明字节完整性 |
| 工程复现 | 固定 seed、严格 schema、稳定 finding codes、确定性构包 | 合成内测不能外推为工业效果 |

## 需要主动披露的评审风险

1. 当前五个专家角色使用同一个确定性 AI 专家系统后端，属于可审计模拟角色，不是真人专家，也不是五个独立模型；角色共识不构成证据。
2. 冻结 Demo 指标来自程序化隐藏真值。它可以证明闭环可证伪、可复算，不能证明真实工厂泛化能力。
3. 真实目标用户和行业价值仍需客户访谈、shadow test 或受控真实数据验证；当前不能填写企业采用、节省成本或生产部署。
4. CycloneDX SBOM 与许可证元数据清单已生成，但顶层 LICENSE、正式 NOTICE、真实数据授权与官网提交回执仍是彼此独立的门槛，不得由代码测试替代。

## 头脑风暴会回放访问边界

- 用户提供的回放页：<https://shanji.dingtalk.com/app/transcribes/76327569643339353235353032365f34303537393032395f39>
- 公开 HTML 返回 HTTP 200，页面元信息标题为“头脑风暴会-会场1”。
- 全新访客浏览器随后被重定向到钉钉统一身份认证；本轮没有取得转写正文、AI 纪要或音视频内容。
- 因此本项目的需求判断不引用或改写该回放正文。若后续由授权账号导出转写，应另存来源、导出时间和访问权限，并重新做差异对齐。

## 当前推荐路数

保持“确定性工具负责测量、AI 专家系统负责解释与质询、冻结 Policy 负责放行”的三层结构，并以 AgentTeams 的 Team / Room / Task / Identity / Skill 作为协同契约。它比泛聊天或单点问答更符合 Agent Infra 闭环要求，也能在没有真人材料专家、外部 API 和真实企业数据的情况下完成可审计演示。后续若接入语言模型，应作为可替换解释器，并披露模型、发送字段、成本和失败降级；不得让模型覆盖工具数值或门禁策略。
