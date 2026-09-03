# VisionData Gate｜产品与开发者导航

VisionData Gate 是一个本地优先的工业视觉数据治理工作台。它把图像、标注、metadata、批次、工单、工艺与视觉方案组织成版本化案件，让确定性工具负责测量、受控 Agent 负责补证规划、具名人员负责高风险决定，最后由 Child Run 按同一合同复验。

公开 GitHub Pages 是隐私安全的 `PUBLIC_SYNTHETIC_REPLAY`；连接本地 FastAPI 后端后，工作台才会读取授权数据源、案件、CAPA 与治理指标。两种模式共用前端路由，但证据来源不会混用。

## 从哪里开始

| 你想完成的事情 | 推荐入口 |
|---|---|
| 在本机启动完整工作台 | [运行说明](RUNNING.md) |
| 调用 REST API | [API Quick Start](API_QUICKSTART.md) |
| 理解 Agent 的权限与状态机 | [Agent Runtime](AGENT_RUNTIME.md) |
| 扩展工业 Skill 或数据适配 | [工业 Skill SDK](INDUSTRIAL_SKILL_SDK.md) · [开放复用合同](OPEN_REUSE_CONTRACTS.md) |
| 配置自有模型 / API Key | [外部模型配置](EXTERNAL_MODEL_CONFIGURATION.md) |
| 核对结果、分母与禁止外推项 | [Evidence & Benchmarks](EVIDENCE_AND_BENCHMARKS.md) · [Claim Scope](CLAIM_SCOPE.md) |
| 审阅安全、隐私与发布边界 | [数据与合规](DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md) · [公开边界](PUBLICATION_BOUNDARY.md) |

## 产品工作流

```text
授权只读来源
  → Evidence Gate
  → 竞争假设与证据缺口
  → 白名单 Worker 补证
  → Frozen Policy Judge
  → 具名人工决定
  → 私有派生整改
  → Child Run 同合同复验
  → 责任队列 + Governed Outcome Envelope
```

工作台会显示 selected/rejected Worker、选择原因、triggering evidence、冻结预算、Tool Receipt、缺失证据和 Parent/Human/Derived/Child 血缘。详情见 [Incident Control Plane](INCIDENT_CONTROL_PLANE.md)、[模型与 Planner 合同](INCIDENT_MODEL_PLANNER.md) 以及 [工具/MCP 合同](TOOLS_AND_MCP_CONTRACT.md)。

## 核心模块

| 模块 | 作用 | 关键边界 |
|---|---|---|
| Incident Kernel v6 | 运行 Intake → Planner → Tool → Council → Judge → Delivery | 仅调用白名单工具和 Worker |
| Deterministic Tool Gateway | 执行图像质量、重复泄漏、标注几何、覆盖与治理合同测量 | 工具事实优先于模型文本 |
| CAPA + Child Run | 将具名选择、批准、私有派生版本与独立复验串成闭环 | 不覆盖 Parent，不自动批准 |
| Governed Audit Envelope | 用 JCS、域分离 SHA-256 与血缘关系绑定内容 | 摘要不是数字签名或可信时间戳 |
| Governed Outcome Envelope | 固定投影 Parent、Human、Derived、Child 与最终责任队列 | Envelope 不能替代源工件 |
| Evaluation Plane | 将私域 Pilot、公开代理和合成基准按真实分母分轨展示 | 未裁决工厂指标保持 null |

协议细节见 [Governed Audit Envelope](GOVERNED_AUDIT_ENVELOPE.md)、[Governed Outcome Envelope](GOVERNED_OUTCOME_ENVELOPE.md) 与 [重放/迁移](TOOL_REPLAY_AND_MIGRATION.md)。

## 当前验证边界

### Omni 私域离线 Pilot（历史）

- 只读 profile：4,464 images / 1,439 masks；
- 固定 Gate：180；
- Parent → Child findings：49 → 33；
- 责任项：6 closed / 43 open；
- 整改后通过：0/1，终态转人工调查。

它证明产品链能处理操作者声明授权的真实字节并保留失败关闭，不等于客户数据、在线工厂 shadow、生产恢复或 ROI。工厂误放行率、误拦截率仍为 `NOT_MEASURED_PENDING_ADJUDICATION`，对应 numerator、denominator、value 与置信区间均保持 null。

### VisA 公开工业代理（RC5）

2026-09-03 已在 RC5 当前环境完成 300 clean + 300 programmatic block 正式复验：

- 600 episodes；
- Dynamic / Fixed 正确终态均为 525/600；
- unsafe release 均为 0；
- 瞬时故障恢复均为 150/150；
- 工具调用 2,550 vs 2,700；
- 不可恢复故障冗余重试 0 vs 150。

语义摘要：

- report semantic SHA-256：`1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c`；
- implementation receipt semantic SHA-256：`7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf`。

该运行只证明合同感知的有界恢复效率；它不证明 Worker replanning、工厂指标、自然缺陷检测精度、真实故障分布或客户 ROI。原始 VisA 字节和本机报告路径不进入公共仓。

### 合成编排

DynamicBench-v3 在 8 个冻结冲突、故障、不确定性与正常夹具上比较 Dynamic 与 Fixed 的编排行为；结果和分母见 [DynamicBench-v3](DYNAMICBENCH_V3.md)。DynamicBench-v1 是历史动态触发协议，不与 v3 或 VisA 合并。历史 `_05` 表示已执行但未恢复的 CAPA/Child，`_06` 将当前候选池可行性标为 `NOT_ESTIMABLE`。

## 安全默认值

- 原始来源只读，整改只进入私有派生版本；
- API Key 保留在本机服务端，不进入浏览器 bundle、公开 Pages 或 Git；
- CAPA、根因和生产放行由具名人员决定；
- `production_release_allowed=false`、`machine_write_permitted=false`；
- 缺证、冲突、预算耗尽、摘要漂移或工具失败时 fail closed；
- 公开导出排除客户原图、mask、设备帧、私域回执、本机路径和个人信息。

## 文档地图

### 使用

- [运行说明](RUNNING.md)
- [API Quick Start](API_QUICKSTART.md)
- [Product Kernel CLI](PRODUCT_KERNEL_CLI.md)
- [外部模型配置](EXTERNAL_MODEL_CONFIGURATION.md)

### 架构与扩展

- [Agent Runtime](AGENT_RUNTIME.md)
- [Incident Control Plane](INCIDENT_CONTROL_PLANE.md)
- [模型与 Planner 合同](INCIDENT_MODEL_PLANNER.md)
- [工业 Skill SDK](INDUSTRIAL_SKILL_SDK.md)
- [开放复用合同](OPEN_REUSE_CONTRACTS.md)
- [工具与 MCP 合同](TOOLS_AND_MCP_CONTRACT.md)

### 证据与治理

- [Evidence & Benchmarks](EVIDENCE_AND_BENCHMARKS.md)
- [Governed Audit Envelope](GOVERNED_AUDIT_ENVELOPE.md)
- [Governed Outcome Envelope](GOVERNED_OUTCOME_ENVELOPE.md)
- [Claim Scope](CLAIM_SCOPE.md)
- [数据来源与合规](DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md)
- [公开边界](PUBLICATION_BOUNDARY.md)
- [第三方许可证清单](THIRD_PARTY_LICENSE_INVENTORY.generated.md)

### GOAI 2026

- [复赛指南核验](GOAI_SEMIFINAL_GUIDE_20260902.md)
- [评分证据索引](GOAI_SCORE_EVIDENCE_INDEX.md)
- [官方反馈闭环](GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md)
- [评审就绪矩阵](REVIEWER_READINESS_MATRIX.md)

本页只导航已经公开 allowlist 覆盖的文档，不链接私域 receipt、release、evidence、`10_reports/` 或本机生成物。
