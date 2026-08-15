# VisionData Gate 终版工程 QA 报告（项目本质与评审信号复核）

核验日期：2026-08-12（北京时间）。机器可读锚点：`10_reports/FINAL_QA_REPORT_20260812.json`；独立 QA 的具体 run ID 与日志保留在包外 detached receipt 和 `deliverables/_qa/`，避免本报告形成自引用。

## 结论

项目继续定位为 **GOAI Agent Infra / 新质基座的可复用工业视觉数据发布门禁子系统**，AI+工业制造是行业闭环实例。核心价值不是角色数量，而是任务分解、真实运行时上下文、白名单工具、唯一策略权、正确失败、工单修复、同合同复验与可审计交付。当前没有把本地契约映射写成 hosted AgentTeams/Matrix 回执，也没有把合成数据写成真实工业效果。

## 本轮代码与 UI 变更

- `ContextTransfer` 升级为运行时 ledger：目标任务发出 terminal event 时即时记录 `recorded_event_sequence`、源/目标状态、实际 `output_refs`、两侧 digest、接受依据和 payload SHA-256；不是结束后按 DAG 回填。
- 修复与复验之间增加显式 `system.repair → verification.intake` 因果依赖；完整工业任务图为 24 tasks / 31 dependency transfers。
- `runtime_contract_audit.json` 新增 event 绑定、任务引用一致、digest、接受依据和 failure-safe 检查。
- `tool_ablation_receipt.json` 逐工具生成 typed `skipped` 回执并重算 Policy Judge；首轮与复验共 10 次消融全部 `DEFER`，无一次更宽松。
- `AgentTeamsSnapshot.context_flow`：6 段 manager → leader → worker → council → judge → operator 的协议级 typed payload 流转。
- `AgentTeamsSnapshot.failure_routes`：缺工具、模型无引用、调查工单、生产授权四类关闭路径。
- `SkillContract.quality_metrics / version_history / rollback_strategy`：每个 Skill 都有可度量的回归指标和回滚语义。
- `RuntimeTrace.skill_executions` 与 `skill_qualification_receipt.json`：24 个终态任务逐一绑定实际 Skill ID/版本/合约摘要、调用 Agent、terminal event、输入输出 digest 与资格结论；篡改版本的测试会将回执降为 `PARTIAL`。
- `execution_config_sha256` 进入 RuntimeTrace 与 run ID：同一输入、合同和策略下，不同工具权限/预算配置拥有不同运行身份，避免故障注入与 happy path 的审计 ID 碰撞。
- `KnowledgeHit` 来源治理：`source_type`、`source_version`、`last_verified`、`permission_scope`、`freshness`。
- `RuntimeTrace.approval_handoff` 与 `evidence/approval_handoff.json`：生产范围固定 `external_authorization_required / blocked`，不伪造人工批准。
- UI 增加“评审负路径”开关；交付页新增运行时 Context ledger、Tool Ablation Receipt 表格与下载，并继续提供 AgentTeams、Tool Replay、Runtime Audit 和 Approval Handoff。

## 真实验证结果

| 检查 | 结果 |
|---|---|
| 工业默认闭环 | `RECAPTURE → PASS`；seed `20260812`；24 tasks / 37 events / 31 runtime transfers |
| 负路径 | 单 Worker 缺证据：`DEFER → DEFER`；无自动修复 |
| 双场景持久证据 | `07_results/reviewer_scenario_suite_20260812_v2/`；同输入/合同/策略，happy 与 missing-worker 两包均通过 archive audit；负路径 13 条 deferred context / 6 条 deferred Skill |
| 单元/集成测试 | `98 passed, 1 skipped`（最终独立 QA run ID 以同名 JSON 和 detached receipt 为准）；跳过项是 Windows 无法创建 symlink |
| Ruff | `check PASS`；`format --check PASS` |
| compileall | `PASS` |
| 独立 AppTest | 工业默认场景真实点击跑通；6 tabs、16 个下载动作、evidence ZIP 复审通过；无异常 |
| seed 压力 | `seed=0..31`：32/32 真值匹配 |
| 工业场景指标 | 12 个隐藏真值全部召回；额外 1 条 governance 重叠 finding 被显式披露；Precision 0.9231 / Recall 1.0 / F1 0.96 |
| Runtime Contract Audit | `PASS`：event-bound context、任务引用、digest、唯一 Judge、同合同复验均通过 |
| Tool Ablation | 10/10 消融均 `DEFER`，无 more-permissive 结果 |
| Skill Qualification | happy path 24/24 qualified；missing-worker 18 qualified / 6 deferred / 0 rejected；两者回执均 `PASS` |
| Reviewer Readiness | `evidence/reviewer_readiness.json` 五维 `PASS/PARTIAL/OPEN` 矩阵；包含证据入口、外部缺口和评委核验清单，不等于官方评分 |
| 候选包 | 由最终构包脚本重建并在 detached receipt 记录 SHA-256、条目数与 clean extraction 审计 |

## 对标结论边界

`C:/Users/living/Desktop/1111.docx` 与 PPT 模板提供的是官方/导师口径；ProcessPilot 目录提供的是他队自评/工程 QA。它们可以用于反查评审关注点，但不能称为“官方评委逐项评分”。钉钉登录保护回放没有被直接核验。当前仍没有真实客户访谈、shadow test、真实工业数据、现场部署、官网提交回执、hosted AgentTeams receipt 或顶层许可证确认。
