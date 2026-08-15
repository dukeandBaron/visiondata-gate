# GOAI Agent Infra 对标与评审追问审计（2026-08-12）

## 结论先行

当前路线继续留在 **Agent Infra / 新质基座** 更合适，不建议为了“看起来像应用”切换到 Boundless Agents。理由是官方头脑风暴明确要求：已有 Agent 运行框架不能直接作为作品，必须围绕一个真实行业问题形成可协作、可验证的系统；VisionData Gate 已经把 AgentTeams/TeamHarness 作为协同语义，把工业视觉数据发布门禁作为领域任务闭环。

本轮对标没有发现“功能完全缺失”的硬伤，但发现五个容易被评审追问的表达/证据风险，已落到工程：

1. 只展示角色名称，不足以证明协作：现在提供 manager → leader → worker → council → judge → operator 的上下文流转表。
2. 只展示成功修复，容易被质疑为 happy path：UI 新增“评审负路径”开关，缺失必需工具时预期 `DEFER`，并显示正确拒答边界。
3. 生产动作授权边界不够独立：运行轨迹与下载区新增 `approval_handoff.json`，明确 `external_authorization_required / blocked`，不伪造人工批准。
4. Skill 有输入输出但质量治理不够显式：每个 Skill 新增质量指标、版本历史和回滚策略。
5. 知识卡缺少来源治理字段：每条召回卡新增 source type、version、last verified、permission scope、freshness。

## 证据分层（不能混称“评委意见”）

| 证据层级 | 本轮材料 | 能支持的结论 | 不能支持的结论 |
|---|---|---|---|
| 官方/导师口径 | `C:/Users/living/Desktop/1111.docx` 录音转写，P23/P26/P137-P152/P466-P472/P562-P616 | 赛道强调可运行、可验证、可复现；任务拆解、上下文、工具安全、结果验证、失败审批/审计；现有 Agent 必须进入 AgentTeams 协作，Skill/行业问题形成闭环 | 不能当作对本项目的逐项打分；回放无画面，不能核验视觉内容 |
| 官方模板 | `C:/Users/living/Desktop/Agent Infra初赛方案PPT框架模板.pptx` | 评分结构为场景价值 25%、多 Agent 协同 25%、Skill 工程体系 25%、工程落地与安全审计 20%、开源开放 5%；要求架构图、运行证据、失败处理、复用与许可 | 不能证明本项目已获得任何分数 |
| 他队材料 | `D:/blender_render/fuwuwaibao/processpilot/goai_boundless_20260816` 自评/QA | 对标出“PASS/PARTIAL/OPEN”、正确失败、人工基线、审批交付和真实用户证据的高信号做法 | 不能写成官方评委评价，也不能外推到本项目实际成绩 |
| 本地工程 | 本项目 runtime trace、evidence matrix、AppTest、QA | 可验证本地工程候选的实现状态 | 不能替代真实企业访谈、真实工业数据、官网回执或许可确认 |

## 与官方口径逐项反查

| 官方/导师追问 | 当前风险 | 已落地证据 | 状态 |
|---|---|---|---|
| 任务如何拆解、上下文如何传递？ | 仅看 Identity 清单会像“角色包装” | `agentteams_mapping.json.context_flow`；UI “一次任务的上下文流转” | 已补强 |
| Worker 如何执行，Leader 如何汇总？ | 事件有绑定但材料不够直观 | task binding + `ToolTrace/Finding` + Council/Judge 依赖图 | 已验证 |
| 工具/Skill 是否必要、失败怎么办？ | 数量多不等于工程价值 | 白名单、预算、失败路由、每个 Skill 的质量指标与回滚策略 | 已补强 |
| 能否正确失败？ | 成功修复路径过于醒目 | 缺工具负路径：`DEFER`，无旧结果复用、无伪造修复 | 已补强 |
| 高风险动作谁批准？ | 仅有“生产需人工”容易被当作文案 | typed `ApprovalHandoff`，`production_system` + `external_authorization_required` + `blocked` + evidence refs | 已补强 |
| 是否真实用户/企业效果？ | 没有访谈、shadow test、真实工时和现场数据 | README/矩阵明确“待外部验证”，不使用合成 F1 外推 | 未完成（外部） |
| 是否已接入 AgentTeams/Matrix？ | 官方 P562-P574 明确要求现有 Agent 能在 AgentTeams 内协作；仅本地映射仍是硬风险 | v1.2.2 Worker/Team CR、Skill 分发计划、conformance receipt；真实 Matrix 原始回执缺失时强制 `mapped_not_connected` | 静态契约已补强；transport 仍 OPEN |
| 是否已完全开源？ | 许可证尚有 REVIEW_REQUIRED | SBOM 与许可证清单；顶层 LICENSE/NOTICE 待权利主体确认 | 未完成（外部） |

## 竞品/对标项目带来的可复用做法

ProcessPilot 的高信号不在于“更多算法”，而在于把失败、回滚、人工审批、运行指纹和交付哈希都做成一等状态。VisionData Gate 已采用对应原则，但范围保持在本项目的工业视觉数据门禁：

- `RECAPTURE → PASS` 仍是领域闭环；新增缺证据 `DEFER` 作为平行负路径。
- reserve-only repair 保留原始批次；调查工单不伪造自动完成。
- `ApprovalHandoff` 只记录交接需求，不生成企业身份、电子签名或生产批准。
- 证据矩阵保持 `tool → finding → work order → rule check → recheck` 链路，不用 UI 截图替代底层证据。

## 当前禁止过度表述

- 不称为“官方评委已经认可/打分”。本地没有逐项官方评语文件。
- 不称为 hosted AgentTeams/Matrix 已连接；当前是可审计契约映射。
- 不称为真实产线部署、客户收益、工业准确率或生产安全认证。
- 不称为五位真人专家或五个独立模型；Council 角色共享后端且只是 advisory。
- 不称为已完全开源或法律合规审查完成；许可证与权利主体确认仍是外部门槛。

## 最小后续动作

1. 用 UI 的“评审负路径”跑一次并保存 `DEFER` trace，和默认 `RECAPTURE → PASS` trace 并列。
2. 若进入复赛，补充经授权的真实数据或 shadow test；固定人工基线、分母、任务数和失败案例。
3. 按 `docs/AGENTTEAMS_V122_RUNBOOK.md` 启动官方 v1.2.2，保存 Team Active/成员 Ready、Team Room assignment exactly-once 和 `Worker.spec.skills` 原始导出与 SHA-256；全部通过前保持 `mapped_not_connected`。
4. 补齐权利主体确认的 LICENSE/NOTICE，再决定是否公开源码包。
