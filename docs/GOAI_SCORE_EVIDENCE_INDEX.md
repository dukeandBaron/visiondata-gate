# GOAI 复赛评分证据索引

更新时间：2026-09-03

本页只做导航与状态对账，不替代原始运行回执，也不预测官方得分。

## 1. 最新 9 页复赛指南：四项优先核验

最新指南第 3–5 页强调四项结果；它没有重新发布百分比。此前 20 页手册的六维权重继续作为能力索引，见下一节。

| 复赛核验项 | 评委可直接查看 | 当前证据 | 诚实边界 |
|---|---|---|---|
| 行业场景价值 | [行业场景价值](INDUSTRY_SCENARIO_VALUE.md)、[官方反馈闭环](GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md) | 目标用户与流程明确；Omni 私域离线 Pilot、VisA 公开工业代理、DynamicBench-v3 合成编排分轨报告 | 没有客户验收、在线工厂 shadow、生产 KPI 或 ROI |
| Demo 与应用验证 | [公开评审首页](https://dukeandbaron.github.io/visiondata-gate-public/)、[60 秒脚本](DEMO_60S_SCRIPT_SEMIFINAL.md) | 14 个公开路由；Worker 选择、触发证据、异常处理、人工闸门、Parent/Child 与 SHA 校验可见 | 公开页面是 `PUBLIC_SYNTHETIC_REPLAY`，无私域后端、账户、密钥或生产写操作 |
| 工程与材料可核验性 | [运行说明](RUNNING.md)、[Agent Runtime](AGENT_RUNTIME.md)、[Evidence & Benchmarks](EVIDENCE_AND_BENCHMARKS.md) | Incident v6、typed contract、确定性工具、Frozen Judge、ETag/JCS/SHA-256、锁文件、测试与构包合同 | 内容绑定不是数字签名；本地/合成结果不等于第三方采用 |
| 数据与合规边界 | [数据来源与合规](DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md)、[公开边界](PUBLICATION_BOUNDARY.md)、[Claim Scope](CLAIM_SCOPE.md) | 来源只读、私有派生整改、API Key 本机保管、隐私门、人工专属生产决定 | 操作者授权声明不等于独立权属认证或原始数据再分发许可 |

四项提交物对应：更新版 PPT/PDF、可运行 Demo 或视频、代码仓库/工程材料、数据来源与合规说明。答辩窗口为 **3 分钟陈述 + 1 分钟 Demo + 3 分钟问答 + 1 分钟评分切换**。

## 2. 此前 20 页手册：六维能力索引

| 维度 | 权重 | 主证据入口 | 当前裁决 |
|---|---:|---|---|
| 行业场景价值 | 25% | [行业场景价值](INDUSTRY_SCENARIO_VALUE.md)、下方三轨证据 | `PARTIAL_STRONG`：问题、用户和本地流程成立；客户 KPI 待真值 |
| Agent 能力与任务闭环 | 25% | [Agent Runtime](AGENT_RUNTIME.md)、[DynamicBench-v3](DYNAMICBENCH_V3.md)、[Outcome Envelope](GOVERNED_OUTCOME_ENVELOPE.md) | `PASS_LOCAL`：Intake → Planner → Tool → Council → Judge → Delivery → Human/CAPA/Child |
| 产品体验与 Demo | 20% | [公开 Pages](https://dukeandbaron.github.io/visiondata-gate-public/)、[Demo 脚本](DEMO_60S_SCRIPT_SEMIFINAL.md) | `PASS_PUBLIC_SYNTHETIC_REPLAY`；本地工作台与公开回放边界分离 |
| 技术实现深度 | 15% | [Evidence & Benchmarks](EVIDENCE_AND_BENCHMARKS.md)、[审计封套](GOVERNED_AUDIT_ENVELOPE.md) | `PASS_LOCAL_ENGINEERING`；GitHub Actions clean checkout/build 已通过 |
| 安全、合规与可追溯 | 10% | [合规说明](DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md)、[公开边界](PUBLICATION_BOUNDARY.md) | `PASS_LOCAL_BOUNDARY`；`human_only`、fail-closed、原始数据不公开 |
| 开放 / 复用贡献 | 5% | [开放复用合同](OPEN_REUSE_CONTRACTS.md)、SBOM、Schemas、Rule Packs、Skills、Adapters | `PUBLIC_SOURCE_AVAILABLE`；独立用户采用仍待外部回执 |

权重来自此前 20 页手册；最新 9 页指南只强化复赛核验与交付，不应被写成再次发布了这组六维权重。

## 3. 三条证据轨：不得合并分母

### A. Omni 私域离线 Pilot

```text
source_profile          = 4,464 images / 1,439 masks
fixed_policy_gate       = 180 images
parent_to_child         = 49 -> 33 findings
responsibility_items    = 6 closed / 43 open
remediation_pass_rate   = 0 / 1
factory_false_release   = NOT_MEASURED_PENDING_ADJUDICATION
factory_false_block     = NOT_MEASURED_PENDING_ADJUDICATION
```

这是操作者声明授权的本地离线 Pilot。它证明真实字节能进入只读 Source Profile、Gate、具名 CAPA、私有派生版本和 Child Run；它不是客户数据验收、在线 shadow、独立权属认证或生产恢复。findings 下降后仍转人工调查。

### B. VisA 公开工业代理（RC5 当前环境正式复验）

```text
evaluated_at                     = 2026-09-03
status                           = PASS
evaluation_boundary              = PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH
episodes                         = 300 clean + 300 programmatic block = 600
terminal_correct                 = 525 / 600 dynamic; 525 / 600 fixed
unsafe_release                   = 0 for both
transient_recovery               = 150 / 150 for both
tool_calls                       = 2,550 dynamic / 2,700 fixed
nonretryable_redundant_retries   = 0 dynamic / 150 fixed
report_semantic_sha256           = 1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c
implementation_semantic_sha256   = 7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf
```

这里的治理真值只来自程序化注入的跨 train/test 精确重复。2026-09-03 的 300+300 正式运行已在 RC5 当前环境复验为 `PASS`；Dynamic 与 Fixed 正确终态相同，因此不支持“Dynamic 更准确”的结论。唯一正向差异是 Dynamic 在 unsafe release 同为 0 的前提下，少做 150 次不可恢复故障冗余重试。

自然产品异常、模糊、曝光和近重复没有人工裁决，因此不进入工厂误放行/误拦截分母。该轨只证明合同感知的有界恢复效率，不证明 Worker replanning、自然缺陷检测精度、真实故障分布或客户 ROI。原始 VisA 图像和本机报告路径不随仓库分发；评测入口为 [`tools/run_public_runtime_benchmark.py`](../tools/run_public_runtime_benchmark.py)。

### C. DynamicBench-v3 合成编排

```text
dynamic_terminal_correctness = 8 / 8
fixed_terminal_correctness   = 4 / 8
tool_calls                   = 14 dynamic / 24 fixed
tool_fault_recovery          = 2 / 2 dynamic / 0 / 2 fixed
unsafe_release               = 0 for both
```

独立 Conflict-v1 配对子集报告 Dynamic false release `0/4`、Fixed `4/4`；它与 v3 不是同一协议，分母不得合并。两者只证明冻结合成输入下的编排行为，不证明工厂效果。

## 4. Agent 闭环与安全断点

```text
授权只读输入
→ Intake / typed contract
→ Planner / competing hypotheses / evidence gaps
→ Tool / selected + rejected Workers / budget / triggering evidence
→ Council / evidence reconciliation
→ Frozen Policy Judge / PASS | RECAPTURE | HOLD | DEFER
→ 具名人工决定
→ 私有派生 CAPA
→ Child Run 同合同复验
→ responsibility queue + DecisionPacket v3 + GovernedOutcomeEnvelope v1
```

固定边界：

```text
authority=human_only
production_release_allowed=false
machine_write_permitted=false
official_submission=PENDING
official_evaluation=NOT_EVALUATED
```

## 5. 公开 Demo 与 Release 实时绑定

```text
public_mirror_rc4_sync     = PASS_PUBLIC_RC4_SYNC
source_commit              = 46a7242f9aa746f9b8f0f78b776d662422d32c72
source_tree                = ab27540b18b8d63db6d9db9256fa2b3330f44dfc
public_head                = eb3ef24f7b7df771a4be51a1a3263a060c561db3
pages_workflow             = 33718870200 / SUCCESS
release_tag                = v0.4.0-goai-semifinal-rc4
current_rc5_docs_published = PENDING
```

- [公共仓库](https://github.com/dukeandBaron/visiondata-gate-public)
- [成功的隐私门与 Pages 工作流](https://github.com/dukeandBaron/visiondata-gate-public/actions/runs/33718870200)
- [公开工作台](https://dukeandbaron.github.io/visiondata-gate-public/)
- [RC4 Release](https://github.com/dukeandBaron/visiondata-gate-public/releases/tag/v0.4.0-goai-semifinal-rc4)

RC4 公共镜像 PASS 只绑定上述 source commit/tree、public head 和工作流。本文属于后续 RC5 文档收口，在新的发布回执出现前不能宣称它已经同步到公共镜像。

## 6. 评委 60 秒读取顺序

1. 打开公开首页，确认 `PUBLIC_SYNTHETIC_REPLAY`、`human_only` 与 `production=false`。
2. 进入 Command Center，查看 selected/rejected Workers、原因、预算和 triggering evidence。
3. 查看竞争假设、缺失证据和工具失败后的 fail-closed 状态。
4. 查看 Parent → Human Gate → Derived → Child；公开轨只证明人工闸门必需，不证明具名批准已经发生。
5. 回到本页核对 Omni、VisA、DynamicBench 三个分母和禁止外推边界。
6. 最后检查 Actions、Release 与 `official_submission=PENDING / official_evaluation=NOT_EVALUATED`。
