# VisionData Gate 冻结规格 v1.2.2 对齐版

> 参赛口径：GOAI 赛道二“无界应用 Boundless Agents”与 AI+工业制造；工业视觉数据治理与发布 Agent 是主产品。Agent Infra 和 AgentTeams v1.2.2 / `agentteams.io/v1beta1` 作为可信后台分层验收，静态契约 PASS 不等于 Matrix connected。

## 目标用户与闭环

- 用户：需要把采集图像与标注发布到实验训练池的数据工程/算法团队。
- 输入：批次 manifest、图像、mask 标注、自然语言发布目的（在 Demo 中冻结为数据合同）。
- 闭环：合同解析 → 白名单工具 → AI Expert Council → 确定性门禁 → 工单 → reserve 模拟补采/重标 → 复验 → 报告与哈希包。
- 决策：`PASS / QUARANTINE / RECAPTURE / DEFER`。

## 初赛范围

只承诺图像质量、重复/跨 split 泄漏、标注结构与覆盖矩阵。初赛已提供 170.02 秒自动演示视频；点云与真实现场视频仍是后续插件。项目不判断真实零件是否合格。

## AI 角色

1. AI 数据合同专家
2. AI 采集质量专家
3. AI 重复与泄漏专家
4. AI 标注与覆盖专家
5. AI 反方审计专家
6. 确定性 Policy Arbiter
7. Audit Clerk

同一后端生成多个意见不视为独立证据。数值只能来自白名单工具，关键缺证据或工具失败必须 `DEFER`。

## 固定验收门槛

- 一个固定 seed 的脏批次不得错误 `PASS`。
- 工单与隐藏 reserve 完成模拟修复后必须正确 `PASS`。
- 关键结构型问题召回率必须为 1.0；整体问题级 F1 必须报告，不可省略失败项。
- 同输入、同合同、同版本的 JSON/CSV/HTML/ZIP 应字节可复现。
- ZIP 必须通过路径、凭据模式、manifest、SHA-256 和清洁解压测试。
- 自动 PASS 仅限 `sandbox_experiment_training_pool`，生产前始终需要真实授权主体。
- 每个终态任务必须具有 Skill 运行资格回执；静态 `SKILL.md` 不能替代调用证据。
- 每条 DAG 依赖必须在运行时形成 `ContextTransfer`，失败上游只能 `deferred`。
- 逐工具 replay 与 ablation 不得得到更宽松决策；执行权限配置进入 run ID。
- AgentTeams v1.2.2 资源必须通过静态 conformance；只有 Team Active、成员 Ready、Team Room、Matrix assignment exactly-once 与 `Worker.spec.skills` 原始导出文件的 SHA-256 全部通过，才能写 `connected`。

## 声明范围门禁

- 已验证：合成本地闭环、双场景 fail-closed、Skill Qualification、ContextTransfer、Tool Replay/Ablation、确定性构包。
- 部分完成：AgentTeams v1.2.2 Worker/Team 资源与 Skill 分发契约已实现，真实 Matrix runtime receipt 未获得。
- 不可本地伪造：真实客户、真实工业数据、生产部署、平台提交回执、权利主体许可证决定。
- 赛事来源：`1111.docx` 是头脑风暴会录音转写且没有画面；只据此引用语音内容，不声称核验视觉演示。
