# GOAI 赛事材料 × VisionData Gate 适配说明

> 版本：2026-08-12。本文只记录已读取的赛事公开页面、用户提供的赛事解读 PDF 与 `1111.docx` 录音转写，及其与本地工程证据的对应关系。用户已确认该钉钉回放没有画面；本文已完整审阅录音转写，但不声称核验任何视觉内容，也不把本地测试写成官网提交或真实工业验收。

## 一、赛道选择结论

当前作品应优先提交 **Agent Infra / 新质基座**，并把 **AI+工业制造** 写成底座的行业验证实例，不建议把作品改投 Boundless Agents / 无界应用。

理由是当前系统的核心价值不是面向一线车间用户提供一个单点应用，而是把一个工业视觉数据发布任务组织成可复用的多 Agent 子系统：任务拆解、上下文传递、白名单工具、证据委员会、确定性门禁、工单、同合同复验和审计交付。它与 Agent Infra 材料中强调的“企业级复杂任务、多 Agent 协同、Skill、工具集成、结果验证、执行证据和安全审计”逐项重合。

Boundless Agents 的 AI+工业制造方向强调设备、质量、工单、库存、排产和供应链协同，并要求面向真实用户与真实业务流程形成可运行应用。VisionData Gate 当前的边界是“图像与标注进入沙箱实验训练池前的发布门禁”，不是设备运维、产线质量判定或生产排程系统；强行改投会要求新增真实系统接入与业务验证，反而削弱当前工程证据链。因此除非报名主体在官网确认改赛道并补充真实工业闭环，否则保持 Agent Infra。

## 二、硬要求到证据的映射

| 赛事材料中的要求 | 本地实现 / 文件证据 | 当前状态与边界 |
|---|---|---|
| 至少 3 个不同职能 Agent | `manager.gate`、`leader.release-gate`、4 个 Worker、`reviewer.ai-council`、`judge.policy`、`operator.repair`、`operator.audit-clerk`；`agentteams_mapping.json` | 已在本地确定性运行中验证；不是多位真人专家 |
| 以 AgentTeams 为协同设计基点 | Team / Room / Task / Identity / Skill 映射；官方 v1.2.2 Worker/Team 资源、`Worker.spec.skills` 分发计划与 conformance receipt | 静态契约 PASS；真实 Matrix runtime receipt 为 OPEN，保持 `mapped_not_connected` |
| Skill 必选且可复用 | Contract Intake、Parallel Evidence Audit、Evidence-Grounded Council、Fail-Closed Policy Judge、Reserve Repair and Recheck 五类 Skill 契约 | 已验证输入、输出、失败处理、安全边界与复用关系 |
| 端到端闭环 | 合同冻结 → Router/Planner → 并行 Worker → Council → Policy Judge → 工单 → reserve 修复 → 同合同复验 → evidence delivery | 冻结合成 Demo 已跑通；不等于真实产线闭环 |
| 工具调用与结果验证 | 图像质量、重复/泄漏、标注、覆盖工具；稳定 finding code；`ToolTrace`、`RuleCheck`、`evidence_matrix.csv` | 数值由确定性白名单工具产生，模型不能覆盖；工具异常会 fail-closed |
| 执行证据沉淀 | runtime trace、事件序列、证据矩阵、canonical JSON、CSV、离线 HTML、manifest、逐文件 SHA-256 | 本地证据可复核；不构成电子签名或数据授权 |
| 高风险动作治理 | `PASS / QUARANTINE / RECAPTURE / DEFER`；Policy Judge 唯一写决策；reserve-only repair；调查工单不伪造完成 | 已验证安全边界；生产动作仍需人工授权 |
| 可观测与持续优化 | Canvas、任务/事件/权限面板、场景规则包、反事实稳定性与工具扰动检查 | 已接入本地 UI 和证据产物；尚未接入云端 AgentLoop/监控平台 |

## 三、对评审最重要的三句话

1. **这是 Agent Infra 的行业子系统，不是重新造一个通用 Agent 框架。** AgentTeams 负责协同语义与运行基点，VisionData Gate 负责工业视觉发布门禁的领域 Skill、工具和策略。
2. **模型负责解释与质询，确定性工具负责测量，Policy Judge 负责放行。** 因而模型幻觉不会直接改写 finding、规则或发布决策；证据缺失时系统拒答或延期。
3. **所有结果都带范围。** `seed=20260809` 的 12 个问题、修复后 `PASS`、以及 seed 0–31 的 32/32，只证明合成数据上的工程可复验性，不外推真实企业收益、真实工业准确率或生产部署效果。

## 四、材料来源与读取边界

- `C:/Users/living/Desktop/1111.docx`：已完整审阅的头脑风暴会录音转写，共 641 段；包含赛道定位、三项硬指标、评审维度、AgentTeams/Skill 说明和常见问题答复。用户确认该回放没有画面，故不存在可核验的视觉演示内容。
- `C:/Users/living/Desktop/Agent infra赛事解读PPT-GOAI世界人工智能开源大赛.pdf`：已解析的赛事解读 PDF，包含赛道要求、提交阶段、评审权重和边界提醒。
- `C:/Users/living/Desktop/AgentTeams：多 Agent 协作与统一管理底座.pdf`：已解析的 AgentTeams 架构与 TeamHarness/Matrix 说明。
- `C:/Users/living/Desktop/Agent_Infra赛道分享-杨翊.pdf`：已解析的赛道分享 PDF，包含 AgentTeams 必须作为协同基点、Skill 必选、工具不按数量评分及“不要只交概念”的说明。
- 官方公开赛道页 `https://www.goaihz.com/tracks?track=infra` 与 `https://www.goaihz.com/tracks?track=apps`：此前已核对公开正文。本轮赛事深度复核以三份 PDF 与 `1111.docx` 录音转写为主，不把音频转写外推成视觉证据。

## 五、提交前仍需外部完成

- 账号持有人确认报名赛道、团队主体、原创声明和平台协议。
- 由权利主体确认顶层 `LICENSE` 与正式 `NOTICE`；当前供应链清单仍有 8 项 `REVIEW_REQUIRED`。
- 在官网上传并保存作品 ID、提交时间和平台回执。
- 如进入复赛，再接入真实或经授权的工业数据/系统，并单独报告真实数据结果；不得用合成 Demo 指标替代。
