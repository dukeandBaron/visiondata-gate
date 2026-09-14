# 工业检测 Agent 项目调研与 VisionData Gate 取舍

调研日期：2026-08-25。本文只把公开仓库、论文摘要和官方参赛手册作为候选证据；
没有复现的论文指标、没有连接的框架和没有明确许可证的代码均不会写成项目已实现能力。

## 1. 赛事约束先于技术选型

权威手册保留在本地授权资料目录，公开材料不记录其绝对路径；文件共 20 页，SHA-256：
`1C01F8860596948D3975B894531FF121C9742AB68B268D92287D7F007DA56D34`。

GOAI 无界应用复赛要求可运行 Demo、完整任务链、代码/工程材料和数据合规说明；评分按
行业场景 25%、Agent 闭环 25%、产品 Demo 20%、技术 15%、安全合规 10%、开放复用 5%。
AI+工业制造额外强调多源融合、流程闭环、解释性、可操作性和安全生产边界。

因此，项目不以“接入最多框架”作为目标，而以以下四个验收问题为主：

1. 中间证据是否真的改变任务图；
2. 裁决能否追到工具、规则、finding 和工单；
3. 工单是否包含责任、技能、前置条件、验收标准和人工节点；
4. 评委能否从界面、API、日志和证据包独立复核。

## 2. 同类项目与可借鉴设计

| 项目/材料 | 公开事实（截至调研日） | 值得借鉴 | 不直接照搬 |
|---|---|---|---|
| [AgentTeams](https://github.com/agentscope-ai/AgentTeams/tree/223ddc2b8073e4c8b93bcbb15e1d717f196c04d9) | Apache-2.0；最新 release 为 [v1.2.3](https://github.com/agentscope-ai/AgentTeams/releases/tag/v1.2.3)；强调 Matrix 房间中的透明协同与 human-in-the-loop | Project DAG、暂停/恢复/重规划语义、干预前快照、时间线和 Worker checkpoint | 当前项目没有 hosted Matrix/AgentTeams transport；只实现本地任务控制和审计语义，状态保持 `mapped_not_connected` |
| [Microsoft agentic-factory-hack](https://github.com/microsoft/agentic-factory-hack/tree/8e42efb5c64ec68b0a8cd579683565c946ffdb0c) | MIT；公开示例围绕预测性维护和多 Agent/MCP 编排 | 遥测→诊断→维修计划→排程→备件的业务链；工具调用、记忆、Trace 和系统交接 | 示例环境不是客户工厂验收；不把其流程或指标冒充本项目实跑 |
| [Azure 工业边缘多 Agent 示例](https://github.com/Azure-Samples/azure-edge-extensions-multi-agent-orchestration-for-industrial-edge-task-processing/tree/4850acee77641b3a3496768183b7d3fb2c90e5b0) | MIT；Planner/Engineer/Executor/Critic 分工，支持边缘执行 | 计划审批、执行前人工确认、预注册安全函数、离线边缘模型 | VisionData Gate 不执行生成代码或设备控制；只读工具白名单更符合当前门禁范围 |
| [DTC Industrial Agents](https://github.com/digitaltwinconsortium/Industrial-Agents/tree/ce02feb32fb3c327da188d4257a7b63a4d427008) | 面向工业 Agent 的公开治理宣言；GitHub API 未声明 SPDX 许可证 | 上下文重放、硬约束、建议与执行分离、完整审计、人工接管、渐进自治和安全降级 | 这是治理参考，不是已认证标准，也不是可直接复制的生产实现 |
| [IBM AssetOpsBench](https://github.com/IBM/AssetOpsBench/tree/0f8afcb5dc6143631ab35652ab68a4729fb89ad5) | Apache-2.0；截至 2026-08-25 的 API 快照约 2,228 stars；公开 IoT、故障模式、时序模型、振动、工单等 MCP server，并提供工业 Agent 场景与评测框架 | 将工业任务拆成领域工具面；把读/写工单权限分离；以固定场景、轨迹和多维评分评估 Agent，而不是只展示一条成功录像 | 它是资产运维 Benchmark/框架，不是 VisionData Gate 已接入的运行时；其场景数、比赛结果和论文成绩都不能作为本项目成绩 |
| [AgentIAD](https://arxiv.org/abs/2512.13671) | 论文提出 Perceptive Zoomer、Web Searcher、Comparative Retriever，通过多轮行动主动补充局部、外部和正常参照证据 | “先观察、再按缺口取证”的工业异常检测 Agent 范式；主动证据获取而非一次问答 | 论文摘要声称同骨干下 MMAD 分类准确率提高 5.92%，本项目未复现；不把论文指标写入项目成绩 |
| [Anomalib](https://github.com/open-edge-platform/anomalib/tree/0da5e4655a64db0638613b6bffa545a5e4acb761) | Apache-2.0；提供异常检测训练、推理、Benchmark 和边缘部署能力 | 可作为未来异常证据后端，按 model/version/weights/threshold 输出标准回执 | 当前 `NOT_CONNECTED`；不能因安装依赖或存在 adapter 就声称完成异常检测 |
| [MMAD](https://github.com/jam-cc/MMAD/tree/1490f887b9570613565fa6a7b15d5f81aa183c54) | ICLR 2025 benchmark；README 披露 8,366 张图像、39,672 个问答；仓库顶层未声明许可证 | 可用于未来多模态解释与问答评测合同设计 | 当前不复制代码/数据进入 Apache 项目，不把 benchmark 结果外推为现场质检能力 |

## 2.1 与近期端到端工业巡检 Demo 的差距审计

这些项目与 VisionData Gate 的赛题形态更接近，因此只比较公开 README 和仓库元数据，
不把 README 自述当成已独立复现的事实。

| 项目 | 公开实现重心 | 对本项目最重要的信号 | VisionData Gate 的差异化边界 |
|---|---|---|---|
| [Multimodal Industrial Inspection Agent](https://github.com/peige-guo/Multimodal_Industrial_Inspection_Agent/tree/495276ce5a0c9af2217d119210f93d939f7cd1dc) | 图像 + 标准文档 + 可选传感器 CSV；RAG、严重度、结构化报告和人工复核；默认视觉后端为 heuristic | “多模态 + RAG + 报告”已是容易复制的 MVP 形态；如果没有证据来源、后端身份和评测分母，功能列表本身不构成优势 | 本项目不做缺陷类型问答；主任务是训练数据发布前的批次门禁，并把每条裁决绑定工具、规则、工单、复验和哈希 |
| [industrial-inspection-agent](https://github.com/AikingChoice/industrial-inspection-agent/tree/d7e814c9bddb5e81dc6bee5257bf5424888b2c12) | MQTT/REST 传感器输入，LangGraph 条件路由，RAG 诊断、降级与工单；README 披露 29 项测试，仓库 API 未声明许可证 | 正常样本绕过 LLM、非法数值前置拒绝、检索/模型降级和低置信度人工复核是合理工业交互基线 | 本项目对应能力是确定性工具优先、失败关闭、计划批准和证据冲突转调查；不宣称已接 MQTT、设备或维修知识库 |
| [multimodal-industrial-inspection-agent](https://github.com/zhanglonglong01/multimodal-industrial-inspection-agent/tree/88be7123cda81f877687515b62e04ea6949885f9) | 图像、历史传感器、RAG、持久 checkpoint、人工批准和受保护 WorkOrder；单列 MetroPT-3 真实传感器负结果与合成多模态结果 | 高完成度作品会把真实/合成、实现/实连、指标/适用范围逐项拆开，并在副作用边界做内容哈希、幂等和恢复 | 本项目已做不可绕过的计划批准、append-only 干预、生产授权 pending 和证据 ZIP；仍不声称 checkpoint 恢复、外部工单系统或真实视觉模型效果 |

截至本次快照，上述三个直接巡检仓库的 GitHub stars 分别为 2、0、0；这既不说明质量高低，
也不进入赛事比较。它们的价值在于暴露产品基线，而非提供可复制的比赛成绩。

## 2.2 同场 TOP30 公开仓库的产品机制核验

本轮又按作品名回到 GitHub API、README、目录与 Actions 核验。以下仓库与海报名称/功能高度
吻合，但公开页面本身不能证明它就是官方提交包；提交身份保持“高可信候选”，不写成官方确认。
所有迁移均为产品机制的独立实现，没有复制对方代码、素材、数据或比赛材料。

| 候选项目与核验快照 | 公开工程事实 | 真正值得学习的机制 | 对 VisionData Gate 的转化 |
|---|---|---|---|
| [VisionDoctor](https://github.com/DarizFish/VisionDoctor/tree/6e5785e095b14564e0d7fa4d44547ca949adb3bc) | Apache-2.0；仓库含端到端、证据完整性、隔离执行、审批与状态机测试；截至快照未见 Actions run | 不确定项进入“待确认问题”，图片观察只作诊断线索，最终通过由独立验证器决定；任何代码合并归人 | 保持工具事实、Agent 解释与 Frozen Judge 分权；新增运行前 `TaskPreflightReport`，来源/权限不明确时在批准前阻断 |
| [FireOps AI](https://github.com/Francischi-ARK/fireops-ai/tree/5dd955919e92cb3091a72fb7de6c30729f4d38b1) | MIT；公开页明确全部为合成演示数据；GitHub Pages 部署成功；仓库有后端测试、运行合同、手机合同与完整参赛材料 | Scenario/Live 明示、事件中枢、设备档案、责任人收件箱、桌面调度与手机现场流程 | 将工业回执提升为“责任队列与验收合同”；界面同时展示当前快照、证据完整性、未闭环工单与人工下一步 |
| [Agrisky AI](https://github.com/XvHaoR/Agrisky-AI-Open/tree/3c97624d7b80a1ae44f6b71d3e4c26e27f171d3d) | Apache-2.0；最新 CI 成功；README 披露 19 项白名单工具、版本化规则、人工归档门禁与服务端敏感数据边界 | 模型只编排，关键数字由确定性引擎计算；归档不在 Agent 工具表；原始敏感字段不送模型 | 继续保持关键裁决由工具/规则产生、生产放行永不进入 Agent 工具；只向产品报告脱敏 profile 和摘要 |
| [ScienceX](https://github.com/insight68/ScienceX/tree/f67037694a2bb32ae17b33425ee65a782b0c0363) | MIT；PR Quality 与开发构建成功，最近一次桌面 Release run 失败；README 明确数据版本、Run lineage、重放与 stale 检测 | 运行证据不仅要可重放，还要在输入产生新版本后标记旧运行过期 | 已实现运行后 `TaskReleaseReadinessReport`：重新计算授权来源 profile；变化后固定为 `BLOCKED_SOURCE_STALE`，禁止复用旧裁决 |
| [Agentero](https://github.com/poco-ai/Agentero/tree/78b0084ec5dd5dc737bd9905264542925ffa714b) | MIT；截至快照 277 stars / 20 forks；有 CI、Release、文档站和大量阅读/标注测试 | 本地 Vault、上下文定位、双链知识图谱比“再加一个聊天框”更利于长期使用 | 当前不引入新的文献系统；后续只考虑把 evidence ref 做成可点击的 finding→工单→规则导航 |
| [CupFlow](https://github.com/MinieShu/CupFlow/tree/97000c6279c0f05fb84f80a4ef2c74833fb50955) | MIT；有 Web/Android 眼镜端和评测文档，快照未见 Actions run | 低置信度不自动推进；纠正后要连续观察到正确操作才继续 | 数据批次不照搬流式迟滞逻辑；可在未来真实回传中要求多次/多责任人一致复验，当前不虚构该能力 |
| [Village of Shadows](https://github.com/mk-tdev/village-of-shadows/tree/3532b0a510a27f3b50486a774f863eacc39fe20c) | MIT + `THIRD_PARTY_NOTICES.md`；仓库含模型 preflight、分支回放、隐私、MCP 与韧性测试；快照未见 Actions run | 开始前验证模型真实消息和工具调用；不可变反事实分支；把图、工具、延迟、成本和记忆做成可观察状态 | 已将分支思想转成工业复验语义：父裁决不可变，整改后创建独立 child Run，边上绑定父请求/证据/合同 SHA；benchmark 反事实仍不冒充产品复验 |

这组同场项目的共同基线已经不是“多 Agent + RAG”，而是：明确模式、状态机、工具权限、
人工副作用门禁、可追溯产物和失败降级。VisionData Gate 的差异必须继续落在“数据发布前门禁 +
证据缺口驱动动态重规划 + 旧证据自动过期 + 可执行责任队列”上。

源码级复核还直接查看了以下公开文件，而不是只读 README：ScienceX 的
[`TaskRunsPanel.tsx`](https://github.com/insight68/ScienceX/blob/f67037694a2bb32ae17b33425ee65a782b0c0363/desktop/src/components/tasks/TaskRunsPanel.tsx)
与 [`scheduledRunReadModel.ts`](https://github.com/insight68/ScienceX/blob/f67037694a2bb32ae17b33425ee65a782b0c0363/src/server/services/localIndex/scheduledRunReadModel.ts)
（Run 列表、增量读取和 source fingerprint 再核验）；Village of Shadows 的
[`branching.py`](https://github.com/mk-tdev/village-of-shadows/blob/3532b0a510a27f3b50486a774f863eacc39fe20c/backend/app/game/branching.py)
（从 checkpoint 克隆出独立 child session，保留 parent 记录）；FireOps AI 的
[`incident-dispatch.md`](https://github.com/Francischi-ARK/fireops-ai/blob/5dd955919e92cb3091a72fb7de6c30729f4d38b1/specs/incident-dispatch.md)
（合法状态迁移、幂等冲突和只追加时间线）；VisionDoctor 的
[`state_machine.py`](https://github.com/DarizFish/VisionDoctor/blob/6e5785e095b14564e0d7fa4d44547ca949adb3bc/src/visiondoctor/workflow/state_machine.py)
与 [`approval.py`](https://github.com/DarizFish/VisionDoctor/blob/6e5785e095b14564e0d7fa4d44547ca949adb3bc/src/visiondoctor/release/approval.py)
（显式状态机、人工批准、候选分支和失败回滚）。这些文件的许可证分别
为 MIT/MIT/MIT/Apache-2.0；本项目只独立实现通用机制，没有复制源码或素材。

## 2.3 调研转化为项目门禁

调研结论只在满足以下条件时进入实现，避免“看过一个项目”被误写成“已经集成”：

1. **工具事实与模型解释分权**：像 AssetOpsBench 的领域工具面一样，图像、标注、metadata、
   manifest 和规则结果必须先形成可校验回执；模型只允许在引用边界内解释。
2. **副作用单独授权**：借鉴受保护 WorkOrder 的思想，建议、复验和生产写回是三个不同状态；
   当前生产写回始终 `pending`，不能被 Agent 结论隐式越过。
3. **真实与合成分母不混用**：Omni 的 source profile、固定 180 Policy Gate、Synthetic-v3 和
   ArchBench-v2 分别报告；没有标签的真实数据不生成精度、召回率或 ROI。
4. **负结果保留**：固定 SOP 多 Agent 必要性不成立、外部模型未连接、全量 Gate 未完成均保留；
   这些边界是可信度的一部分，不从评审材料中隐藏。
5. **先证明业务闭环，再展示 Infra**：评委首先看到授权数据 → 计划批准 → 取证 → 动态补证 →
   裁决 → 工单 → 人工审批；typed task、Skill、Adapter 和 AgentTeams 语义在第二层解释其可复用性。

GitHub Star 数随时间变化，不作为技术正确性或赛事得分证据。调研时 API 快照仅用于发现：
AgentTeams 5,473、Anomalib 6,077、MMAD 272、Microsoft 示例 67、AssetOpsBench 2,228；
这些数字不进入产品主叙事。

## 3. 对 VisionData Gate 的直接结论

### 3.1 应继续强化，而不是换掉的主线

VisionData Gate 的差异化不是“又一个缺陷问答模型”，而是工业 AI 数据进入训练前的可信发布门禁：

```text
授权只读数据源
→ 多源证据（图像、mask、manifest、metadata、工具与规则）
→ 首轮裁决
→ 漂移/分组/冲突触发动态 Worker
→ Frozen Policy Judge
→ 可执行工单
→ 人工生产审批
→ Evidence ZIP / API 交付
```

这条链同时覆盖官方的行业任务、Agent 闭环、产品体验、技术深度和安全边界；Agent Infra
作为支撑层提供 typed task、Skill、工具合同、失败语义、回放和可替换 adapter。

### 3.2 本轮已落地的增强

- `plan_approval_required`：任务可先生成计划预览，批准前不能读取数据或调用工具；
- `TaskPlanPreview`：冻结目标、来源、工具、阶段、动态补证策略和生产权限；
- `task_interventions`：数据库级 append-only 干预时间线，记录操作人、动作、说明、
  变更前状态、变更前快照 SHA-256 和计划 SHA-256；
- `CANCELLED`：只允许尚未执行的计划取消，不伪造长任务的强制暂停/恢复；
- `TaskPreflightReport`：批准前实时核对生命周期、只读授权、source profile、工具白名单、
  确定性 Runtime 与生产权限；前置条件失败时批准接口返回 409，执行器启动时仍二次核验；
- 结果审阅：完成后可记录“确认已审阅”或“要求修改”，但不把它写成生产批准；
- `TaskReleaseReadinessReport`：不修改冻结 Evidence ZIP，实时交叉检查证据哈希、输入快照、
  Gate 结论和剩余工单；运行后数据变化即 `BLOCKED_SOURCE_STALE`，旧结论不得复用；
- `TaskLineageReport`：整改后不改写父任务，而是创建强制人工计划批准的 child Run；继承项目、
  场景规则、工具白名单和固定种子，并用数据库只追加边绑定父 request SHA、Evidence SHA 与
  re-verification contract SHA；`GET /lineage` 可下载完整哈希封印运行族；
- `industrial_delivery_receipt.json`：融合六类证据，将每张工单补充为 AI 专家角色、Skill、
  责任角色、前置条件、验收标准、人工节点、`evidence_span` 和 `reason_trace`；
- API 与工作台：计划、干预时间线和工业交付回执均可查询和下载。

### 3.3 有意不做的内容

- 不为了角色数量再堆 Agent；固定 SOP 的三架构对照已经表明多 Agent 不自动提高质量；
- 不在没有 checkpoint、阈值校准和独立真值集时接入 Anomalib 并展示“高准确率”；
- 不让 Agent 自动改写图像、mask、label、manifest 或控制设备；
- 不把操作者授权声明写成独立法律权属认证；
- 不把本地 AgentTeams 语义映射写成 hosted 服务已连接。

## 4. 复赛演示应证明什么

评委只需在一条主链中验证以下事实：

1. 创建真实授权数据任务，选择“运行前先审核计划”；
2. 在计划页核对工具权限与生产边界，批准后才开始运行；
3. 查看 metadata 数量漂移、原生分辨率组和跨工具处置冲突触发三个新 Worker；
4. 查看最终 `RECAPTURE`、发布就绪门禁、证据矩阵和责任队列与验收合同；
5. 从当前裁决创建独立复验 Run，检查父裁决仍在、child 继承同一合同且重新等待计划批准；
6. 下载 Evidence ZIP 与 lineage JSON，核对 plan/intervention/industrial receipt 和父子 SHA；
7. 最终结果只允许人工“已审阅/要求修改”，生产放行仍为 `pending`。

该演示比单纯展示模型热力图更贴近官方“完整任务闭环、可操作性和安全生产边界”的意图。

## 5. 下一阶段而非当前已完成项

| 增强 | 进入条件 | 验收证据 |
|---|---|---|
| Anomalib/PatchCore 异常证据后端 | 明确数据许可、权重来源、独立 calibration/test split | model identity、weights SHA、阈值回执、逐样本分数/图摘要、误报/漏报分母 |
| 多视角几何后端 | 真实 VGGT/OmniVGGT 服务与模型身份可验证 | model-info、checkpoint SHA、输入批次 SHA、深度/轨迹/重投影回执 |
| hosted AgentTeams | 服务、Matrix 房间和原始运行回执可访问 | Team Active、Worker Ready、Task/Room/Skill assignment 与事件导出 |
| 客户 shadow test | 客户授权、脱敏和验收指标书面确认 | 批次级错误放行率、整改闭环率、时延/成本与签署回执 |

以上条件未满足前，状态分别保持 `NOT_CONNECTED`、`MODEL_NOT_TESTED`、
`mapped_not_connected` 和 `EXTERNAL_ACCEPTANCE_OPEN`。
