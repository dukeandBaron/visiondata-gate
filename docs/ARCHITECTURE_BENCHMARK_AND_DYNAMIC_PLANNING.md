# 同协议架构实验与 Omni 动态规划

> 核验日期：2026-08-13。本文记录工程实验，不把本地确定性运行写成客户、生产或官方评审结果。

## 1. 为什么做三方实验

固定数据检查很容易被包装成“多 Agent”，但多几个角色不等于更好的质量。项目因此冻结以下变量，只改变编排和 AI 审阅方式：

- 相同输入与隐藏真值；
- 相同 `BatchContract`；
- 相同五个白名单工具；
- 相同 Industrial Policy Judge；
- 相同四种等价证据扰动；
- 相同本地机器和确定性后端。

三种架构定义：

| 架构 | 工具编排 | AI 审阅 | 发布裁决 |
|---|---|---:|---|
| 传统流水线 | 并行确定性 DAG | 0 | 同一个 Policy Judge |
| 单 Agent | 单控制器顺序调用 | 1 个通用 AI Reviewer | 同一个 Policy Judge |
| 多 Agent | 并行证据 Worker | 6 个分工 AI Reviewer | 同一个 Policy Judge |

实现入口：`src/visiondata_gate/architecture_benchmark.py`。

## 2. 冻结实验

复跑命令：

```powershell
$env:VISIONDATA_BENCHMARK_FIXTURE_ROOT = 'D:\blender_render\fuwuwaibao\visiondata_gate\tmp'
.venv\Scripts\python.exe -m visiondata_gate.cli architecture-benchmark `
  --output output\architecture_benchmark_20260813_v2\architecture_benchmark.json `
  --seeds 20260809 20260810 20260811 20260812 20260813 20260814 20260815 20260816 `
  --repeats 3
```

协议规模：8 个 seed × 3 次重复 × 4 种扰动 × 3 种架构，共 288 条记录。每个 seed 先分别预热顺序和并行工具路径；之后按 seed、重复和扰动轮换架构执行顺序，降低冷启动和固定顺序偏差。

结果锚点：

- 报告：`output/architecture_benchmark_20260813_v2/architecture_benchmark.json`
- SHA-256：`5a5983f514cbb2ae8ffcfab65122cdf00b969224c25bc7f24cd3d69e67a65654`

| 指标 | 传统流水线 | 单 Agent | 多 Agent |
|---|---:|---:|---:|
| 记录数 | 96 | 96 | 96 |
| 错误放行率 | 0% | 0% | 0% |
| 任务成功率 | 100% | 100% | 100% |
| 扰动稳定率 | 100% | 100% | 100% |
| Precision | 0.9231 | 0.9231 | 0.9231 |
| Recall | 1.0000 | 1.0000 | 1.0000 |
| F1 | 0.9600 | 0.9600 | 0.9600 |
| 平均时延 | 649.006 ms | 474.493 ms | 650.054 ms |
| P95 时延 | 709.512 ms | 522.955 ms | 705.816 ms |
| 相对计算单元 | 5 | 6 | 11 |
| AI 审阅数 | 0 | 1 | 6 |
| 估算输入 Token 单元 | 0 | 2725.75 | 16354.5 |
| 实际模型调用/费用 | 0 / ¥0 | 0 / ¥0 | 0 / ¥0 |

结论：**在这个冻结 SOP 上，多 Agent 没有提高质量、任务成功率或扰动稳定性，因此固定门禁主链本身不能证明多 Agent 必要性。** 多 Agent 的平均时延与传统并行 DAG 接近，但相对计算单元从 5 增到 11，估算审阅输入约为单 Agent 的 6 倍。时延仅是当前 Windows 单机观测，不是生产 SLO。

这个负结论不应删除。它把多 Agent 的合理边界收束为：只有出现不可预先穷举的中间证据、需要新增任务或跨域冲突裁决时，Leader 动态组织 Worker 才可能产生独立价值。

## 3. Omni 真实证据动态分支

实现入口：`src/visiondata_gate/omni_adapter.py::_dynamic_leader_followups`。

Omni Gate 先执行五个静态只读工具和第一次 Policy Judge，再根据实际中间证据动态派发 Worker。动态任务在第一次证据产生前不存在，回执明确记录 `planned_before_initial_evidence=false` 和 `dispatch_mode=parallel_after_initial_judge`。

当前支持三个动态分支：

| 触发条件 | 动态 Worker | 动作 |
|---|---|---|
| 出现 `METADATA_COUNT_DRIFT` | `worker.metadata-reconciliation` | 比对元数据与文件树聚合计数，保留 `INVESTIGATE`，禁止假修复 |
| 原生分辨率组大于 1 | `worker.native-resolution-reconciler` | 验证分组质量证据是否完整；完整则补证，不完整则新增 finding 并 DEFER |
| 同一样本收到多种处置动作 | `worker.remediation-conflict-adjudicator` | 新增 `CROSS_TOOL_ACTION_CONFLICT`，把冲突样本转调查 |

真实 Omni 复跑命令：

```powershell
.venv\Scripts\python.exe -m visiondata_gate.cli omni-gate `
  --root <AUTHORIZED_EXTERNAL_OMNI_ROOT> `
  --source-archive-sha256 773b089c120238599cf5d03d80445130eda63da66750f32555f7ad526b372851 `
  --output <PRIVATE_EVIDENCE_ROOT>\visiondata_gate_omni_dynamic_gate_v1 `
  --per-bucket 2 `
  --seed 20260813
```

真实运行结果：

- 固定 180 张样本；源树 4,464 张图像、1,439 个 mask；
- 初次证据发现 28 个原生分辨率组；
- 元数据总数与文件树相差 15，涉及 3 类；
- 2 个样本出现跨工具处置冲突；
- Leader 动态派发 3 个 Worker，1 次 replan；
- 最终 `RECAPTURE / 45 findings / 45 work orders`；
- 其中 2 份 `INVESTIGATE`；
- GateResult SHA-256：`58387e7dbec4cbbd4e023dca34bfb88708d934097c2db203eb36d13f61cbd057`；
- Dynamic Leader Plan SHA-256：`9e4c5c1a2cb124802219bf6d3fef8a29d66d78d691e1ae81983d1115e623ee03`。

私有证据位于 `D:/blender_render/moxin/_private_evidence/omni_ad_20260813/visiondata_gate_omni_dynamic_gate_v1/`。所有动态回执只包含脱敏样本 ID、聚合计数、引用和哈希；未复制原图/mask，未写出类别名、文件名或私有数据路径。

## 4. 当前严谨边界

- 三方 benchmark 证明固定 SOP 上没有多 Agent 优势，不能反向宣称“多 Agent 已提升 F1”。
- 动态分支证明 Leader 会根据真实中间证据增派 Worker、补证和转调查；它不证明 AgentTeams/Matrix 已连接。
- 动态 Worker 当前为本地确定性 AI Worker，不是外部大模型，也不是人类专家。
- Omni 只完成固定 180 张 Policy Gate；4,464 张图像只完成全树结构/解码审计，不是全量 Gate。
- 实际模型费用为 0；Token 单元只是证据序列化大小的输入代理，不是供应商账单。
