# VisionData Gate × AgentTeams 对齐说明

> 主赛道口径：GOAI 赛道二“无界应用 Boundless Agents”与 AI+工业制造。AgentTeams 是可信后台 adapter，不是应用价值主叙事。

本项目面向工业视觉算法工程师与数据治理团队提供数据审核、补证、工单、复验和证据交付应用；同时将内部角色映射到 AgentTeams 的 Team / Room / Task / Identity / Skill 语义。应用闭环决定需要怎样的协同能力，AgentTeams adapter 让协同契约可替换、可审计，但静态映射不等于 hosted 连接。

## 结论边界

- 已验证：本地运行时可执行 Goal → Manager → Team Leader → Workers → Evidence Council → Policy Judge → Work Order → Reserve Recheck → Evidence Delivery 的闭环。
- 已实现本地协议层：`src/visiondata_gate/agentteams_contract.py` 生成稳定的 Team/Room/Task/Identity/Worker/Skill 映射快照。
- 已实现官方 v1.2.2 资源层：`src/visiondata_gate/agentteams_v122.py` 导出 9 个 `Worker` CR、1 个 `Team` CR、唯一 Team Leader、`Worker.spec.skills` 分发计划与静态 conformance receipt。
- 已接入：每条 runtime event 带有 `agent_id / team_id / room_id / protocol / task_kind` 绑定；Canvas 与 Streamlit 展示该映射。
- 当前状态：默认运行时为本地 deterministic adapter，`connection_status=mapped_not_connected`、`matrix_connected=false`。静态 conformance PASS 只证明资源/Skill 契约可部署；真实 Team Active、成员 Ready、Team Room assignment 和 Skill assignment 原始回执尚未获得。
- 评审追问证据：`context_flow` 显式记录 manager → leader → worker → council → judge → operator 的上下文载荷；`failure_routes` 记录缺证据、模型越权、调查工单和生产授权的关闭路径。
- 动态运行证据：目标任务发出 terminal event 时，`agent_runtime_trace.json#/context_transfers` 即时记录 `recorded_event_sequence`、源/目标 Agent、源/目标 Task 与状态、引用集合、两侧产出 digest、接受依据、payload hash 和 `accepted/deferred`；审计逐边比对 event 与任务 `output_refs`，静态 `context_flow` 只描述协议，动态 ledger 才是本次执行回执。
- Skill 动态证据：`agent_runtime_trace.json#/skill_executions` 和 `skill_qualification_receipt.json` 逐任务记录实际 Skill 版本、合约摘要、调用 Agent、terminal event 与输入输出 digest；版本/越权/事件漂移会使资格失败，错误或跳过任务只能 deferred 并执行声明的回滚策略。
- 生产交接证据：`approval_handoff.json` 固定为 `production_system / external_authorization_required / blocked`，本地 PASS 不生成生产批准或身份回执。
- 连接防伪证据：`agentteams_v122_conformance.json` 只有在三类原始导出文件存在且 SHA-256 匹配时才允许 `connected`；模板值、截图或手填 event ID 都会失败。

## Agent Identity 清单

| Identity | 类型 | 职责 | 允许边界 |
|---|---|---|---|
| `manager.gate` | Manager Agent | 接受目标、创建团队任务、生命周期与权限边界 | 不能替代 Policy Judge |
| `leader.release-gate` | Team Leader | 分解 DAG、分派 Worker、汇总上下文与异常路由 | 不能写入发布决策 |
| `worker.*` | Worker Agent | 对应白名单工具执行可复算检查并产生 Finding/ToolTrace | 不能改合同、任意写文件或 PASS |
| `reviewer.ai-council` | Reviewer | 只解释被引用的工具证据，交叉质询并披露不确定性 | 仅 advisory，不能覆盖工具事实 |
| `judge.policy` | Policy Judge | 执行冻结规则、反事实稳定性和场景阈值 | 唯一可写 GateDecision 的身份 |
| `operator.repair` | Operator | 仅对 reserve 副本执行有限工单并触发同合同复验 | 不修改原始批次；生产动作仍需人工 |
| `operator.audit-clerk` | Operator | 生成 canonical trace、evidence matrix、hash 和交付包 | 只写审计产物，不改变决策 |

## Team / Room / Task 映射

- Team：`team.visiondata-gate` / VisionData Release Gate Team
- Room：`room.visiondata-gate.runtime`，所有身份在同一协作上下文观察事件与状态
- Task：`task.release-gate.<run-id>`，一次运行一个目标，可拆为 intake、route、memory、plan、tool、council、judge、repair、verify、delivery
- Protocol：`agentteams-teamharness.v1`
- Runtime adapter：本地 `local-deterministic`；未来可由 Matrix/远程 Runtime adapter 替换，领域 Worker 与 Policy 契约不变
- Official deployment contract：AgentTeams v1.2.2，commit `aa650ccacc2ba6171d1b0b5efd2a49b1472abe5d`，API `agentteams.io/v1beta1`

## 可复用 Skill 契约

| Skill | 输入 | 输出 | 失败处理 | 安全边界 |
|---|---|---|---|---|
| Contract Intake v1 | goal、manifest、contract | input hash、validated context | schema/path/missing input → DEFER | 只读，不授予生产权限 |
| Parallel Evidence Audit v1 | context、allowlist、budget | ToolTrace、Finding、metrics | tool error/permission/budget → fail-closed | Worker 不能写决策/合同 |
| Evidence-Grounded Council Review v1 | findings、traces、knowledge | opinions、cross-examination、limitations | unreferenced claim/timeout/invalid JSON → deterministic fallback | 仅 advisory |
| Fail-Closed Policy Judge v1 | findings、traces、council、scenario | GateDecision、RuleCheck、WorkOrder | missing evidence/skipped tool/drift → DEFER/RECAPTURE | 只有 Judge 能写发布决策 |
| Reserve Repair and Recheck v1 | work orders、reserve、contract | repaired result、verification evidence | investigate-only/repair mismatch → 保持原批次并复验 | 不修改原始批次 |

## 评审对齐

| Agent Infra 要求 | 本项目证据 |
|---|---|
| 至少 3 个不同职能 Agent | Manager、Team Leader、4+ Worker、Reviewer、Judge、Operator |
| AgentTeams 为协同基点 | `agentteams_mapping.json`、事件绑定字段和 Team/Room/Task IDs |
| Skill 必须可复用 | 五个 Skill 的输入/输出/依赖/失败/安全契约 |
| 任务拆解与状态追踪 | `runtime_trace.tasks`、`runtime_trace.events`、Task bindings |
| 结果验证与证据沉淀 | `evidence_matrix.csv`、`reason_trace`、canonical JSON、SHA-256 |
| 上下文流转可审计 | `context_transfers` 边数与 Task dependencies 一致；payload hash、源/目标产出 digest、实际 `output_refs` 与 deferred 原因可校验 |
| 高风险动作审批/回滚/审计 | fail-closed Policy Judge、reserve-only repair、DEFER、boundary notice |
| 开放复用价值 | 稳定 JSON schema、工具白名单、Skill 清单、离线证据包 |

## 不应宣称的内容

- 不应把本地映射快照称为已连接 AgentTeams/Matrix 服务。
- 不应把 deterministic synthetic seed 的 Precision/Recall/F1 外推为真实客户或工业数据效果。
- 不应把 `PASS` 写成生产发布、零件合格、数据授权或安全认证。
- 不应把 AI Council 的多个角色写成真人专家或多个独立模型。

## 运行后关键产物

```text
evidence/agent_runtime_trace.json
evidence/agentteams_mapping.json
evidence/agentteams_v122_resources.yaml
evidence/agentteams_v122_skill_distribution.json
evidence/agentteams_v122_conformance.json
evidence/claim_scope_receipt.json
evidence/initial/evidence_matrix.csv
evidence/initial/rule_package_snapshot.json
evidence/repaired/evidence_matrix.csv
evidence/demo_summary.json
```

这些文件共同构成“角色→任务→工具→finding→rule check→工单→复验→交付”的审计链；单独的 UI 截图或单独的模型回答不构成闭环证据。
