# 评审场景矩阵（本地可复现）

这份矩阵把“看起来能跑”转换成可被评审逐项追问的失败证据。每个场景都使用同一
`agent-demo` 入口和同一 typed contract；不同之处只在权限、工具顺序或输入证据。
矩阵不声称已经覆盖真实客户或真实产线。

| 场景 ID | 注入方式 | 预期决策/闸门 | 证明的边界 | 当前验证入口 |
|---|---|---|---|---|
| S01 happy-loop | 默认四个 Worker，seed=20260812 | `RECAPTURE → PASS` | 正常闭环、工单与同合同复验 | `agent-demo --seed 20260812` |
| S02 missing-worker | `allowed_tools=[image_quality]` | `DEFER → DEFER` | 缺证据不补写、不沿用历史 PASS、不伪造 repair | `tests/test_agent_runtime.py::test_missing_worker_permission_stays_deferred_without_fake_repair` |
| S03 tool-error | 工具异常/不可解码 | `DEFER` 或 `RECAPTURE` | ToolTrace error 进入 Policy Judge，Council 不能覆盖 | `tests/test_policy_agents.py` |
| S04 evidence-tamper | 修改 finding/tool result 后重算校验 | `DEFER` | 证据哈希/引用链不一致时拒答 | `tests/test_evidence_package.py` |
| S05 tool-reorder | 同一 finding 的工具顺序重排、去重 | 规则结论保持或显式报告 drift | 检查工具级反事实稳定性，不把顺序当证据 | `tests/test_policy_agents.py::test_scenario_profile_tool_counterfactual_is_stable_for_same_finding_traces` |
| S06 prompt-injection | 模型输出含未引用结论 | 仅 advisory；决策仍由确定性 Judge | 语言模型不能覆盖 ToolTrace/RuleCheck | `tests/test_policy_agents.py` |
| S07 approval-missing | 请求 production scope 且无外部授权 | `blocked` | 生产写回不由本地 Agent 或 PASS 代替 | `approval_handoff.json` |
| S08 rollback-failure | reserve repair 不满足同合同复验 | 保留原批次并进入调查/人工路径 | repair 是副本操作，失败不抹掉原始证据 | `tests/test_repair_evaluation.py` |

## 评审读取顺序

1. 先看 `observability_summary.json`，确认事件、任务、工具调用和绑定是否完整。
2. 再看 `proof_index.json`，从 claim 跳到 `GateResult`、`evidence_matrix`、`approval_handoff`。
3. 最后对比 initial/repaired 两套 evidence matrix，确认 finding → work order → rule check → recheck 没有断链。

## 诚实边界

- 这些是本地 deterministic adapter 的可复现场景，不是 hosted AgentTeams/Matrix 回执。
- 合成数据指标只证明固定 fixture 上的工程正确性，不代表真实工业准确率或客户收益。
- “工具重排稳定”只在矩阵列出的受控扰动下成立；不能外推为任意输入下的鲁棒性。
