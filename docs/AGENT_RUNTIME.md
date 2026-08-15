# Agent Runtime v2

> GOAI 赛道二应用后台说明：VisionData Gate 是 AI+工业制造的工业视觉数据治理与发布 Agent；Runtime 为应用提供动态补证、失败关闭与证据交付能力。本地运行显式披露 `mapped_not_connected`，不冒充 hosted AgentTeams/Matrix。

## 目标

VisionData Gate Runtime v2 把工业视觉数据审核实现为有界、可观察、可失败关闭的 Agent 应用，而不是把多个角色名称包装成一次规则函数调用。它服务于工业制造数据批次的检查、补证、工单、复验和证据交付；Infra 只作为后台可信能力。本文件描述本地产品实现，不代表官网提交、客户验收或真实工厂效果。

## 运行链路

1. **Task Trigger** 接收目标、数据合同和 manifest。
2. **Router** 将目标收束为 `industrial_vision_data_release_gate`，拒绝把数据发布结论扩展成产品质量或生产授权。
3. **Memory Broker** 召回本轮上下文、长期运行摘要、项目语义知识卡和角色约束。
4. **Planner** 生成显式依赖图，选择白名单工具并应用工具/模型预算。
5. **Workers** 并行执行图像质量、重复泄漏、标注完整性和覆盖矩阵四项只读工具。
6. **Tool Gateway** 在调用边界重新校验 Pydantic 合同，记录输入/输出哈希和稳定 finding codes。
7. **AI Expert Council** 由五个角色分别解释证据并交叉质询。默认使用本地确定性证据推理，也可以接入 OpenAI-compatible 模型。
8. **Policy Judge** 使用冻结、fail-closed 策略输出 `PASS / QUARANTINE / RECAPTURE / DEFER`；模型只有建议权。
9. **Repair Orchestrator** 仅对可执行工单使用隐藏 reserve 模拟修复；调查工单不会被伪造为自动完成。
10. **Recheck** 在同一合同、同一工具集合下重新运行整条门禁链路。
11. **Evidence Delivery** 写出 GateResult、报告、runtime trace、记忆快照和 canonical JSON。
12. **Context Transfer Receipt** 在目标任务发出 terminal runtime event 时即时写入本次 DAG 的依赖边：`recorded_event_sequence`、源/目标 Agent 与任务、源/目标状态、输入/输出引用、两侧产出 digest、接受依据、payload SHA-256 和 `accepted/deferred`。审计会把事件、引用与实际任务 `output_refs` 做逐边比对；它是运行时 ledger，不是运行结束后按静态 DAG 回填的展示表。

## 任务图与并行性

每次门禁包含 10 个任务节点：intake、route、memory、plan、四个 tool Worker、council 和 judge。完整首轮+修复+复验+交付共 22 个节点。四个检测 Worker 使用 `ThreadPoolExecutor` 真正并行运行，结果按冻结工具序号重新排序后再送入 Judge，避免并发完成顺序改变门禁结果。

## 模型后端

### 本地确定性证据推理

- 无网络、无 API Key、可重复。
- 五个角色使用不同关注域、证据筛选、质询和建议规则。
- 明确披露共享后端；角色一致意见不算独立证据。

### OpenAI-compatible

- 接收标准 Chat Completions JSON。
- 每个角色单独调用，输出必须通过 `AgentOpinion` 结构校验。
- Claim 必须引用允许的 evidence ref；无引用、无效 JSON、超预算或请求失败时，单角色回退到确定性证据推理。
- 本机 HTTP 端点可用；非本机必须显式授权且只能使用 HTTPS。
- API Key 只存在于本轮内存，不写入配置、事件、证据或长期记忆。
- 模型无法直接访问文件系统，无法修改合同、工具结果和 Judge 决策。

## 五层记忆

- **Working**：当前 goal、seed、batch、首轮与复验决策。
- **Session**：本轮公开事件摘要；不保存隐藏 chain-of-thought。
- **Long-term**：最多 20 条运行摘要，只含决策、finding codes、完成工具和后端。
- **Semantic**：项目定义的合同、工具能力和安全边界知识卡，来源使用 `project-policy://...`。
- **Role**：Router、Planner、Workers、Council 和 Judge 的稳定角色约束。

## 权限与失败恢复

- 工具调用必须同时通过静态白名单和本轮 `allowed_tools`。
- 关闭必需工具或耗尽预算会生成 `skipped` trace，Judge 输出 `DEFER`，不会复用旧结果。
- 工具异常生成 `error` trace；没有完整证据时禁止 PASS。
- 模型不可用不会阻塞硬检测，Council 降级并在 runtime trace 中记录 `fallback_used`。
- 包含 `INVESTIGATE` 的工单不会进入模拟自动修复；系统保留原批次并执行 fail-closed 复验。
- 上游任务失败、目标任务跳过或错误、或上游没有真实产出引用时，依赖边的上下文状态为 `deferred` 并带 `rejection_reason`；审计检查拒绝“失败边被当成成功传递”以及“凭空补写引用”。
- Windows 目录发布使用已验证目标不存在条件下的 `os.rename`，避免 `os.replace(directory, directory)` 的 `WinError 5`。

## UI

Streamlit 工作台提供：

- 自包含 HTML5 Canvas 拓扑和动画数据流；节点状态来自真实任务 trace。
- Goal、模型后端、远程授权、API Key 内存输入、Worker 工具权限和预算控制。
- 任务依赖、权限、耗时、事件序列、证据引用、专家质询、知识召回和五层记忆面板。
- 离线 HTML、GateResult JSON 和完整证据 ZIP 下载。
- 评审负路径开关可限制为单个 Worker，缺失必需证据时展示 `DEFER`；不会复用历史 PASS 或伪造修复。
- AgentTeams 面板展示一次任务的 `context_flow`、失败路由与 Skill 质量指标/版本回滚策略。
- `agent_runtime_trace.json#/skill_executions` 与 `skill_qualification_receipt.json` 将 Skill 从静态说明升级为运行时回执：每个终态任务绑定 Skill ID、版本、合约摘要、Agent、terminal event、输入输出引用/digest 和资格结论；失败任务必须 deferred 并给出回滚动作。运行 ID同时绑定 execution-config SHA-256，防止同输入不同权限/预算配置发生身份碰撞。
- 交付区输出 `approval_handoff.json`，明确生产范围仍为 `external_authorization_required`，不把本地运行误称为人工批准。
- 运行契约审计同时输出 `context_transfers` 统计和每条边，供评委从 task → payload → tool/finding → Judge 逐跳复核。

Canvas 不依赖 CDN 或外部字体，通过 `st.iframe` 的 data URL 加载，因此离线可运行。
