# Benchmark Suite — 实验驱动的设计

VisionData Gate 用一组目标不同的实验解释架构取舍：先判断固定流程何时足够，再检验按证据补查、顺序稳定性、异常恢复和真实产品调用链。各协议保留自己的输入和指标，不拼接成一个总准确率。

| 基准 | 验证问题 | 已记录的关键发现 | 入口 |
|---|---|---|---|
| Synthetic-v3 | 检查、派生整改、独立复验能否完成 | 12 个注入问题，初始 RECAPTURE、派生复验 PASS；合成 F1 1.00 | [运行指南](../docs/LIVE_REPRODUCTION.md) |
| ArchBench-v2 | 固定 SOP 是否需要多 Agent | 3 架构、288 条记录，质量持平；为按需使用复杂编排提供依据 | [实现](../src/visiondata_gate/architecture_benchmark.py) |
| DynamicBench-v1 | 按证据触发是否减少无效补查 | 相比固定多 Agent 少 57 次无效补证；与单 Agent 质量持平，本机 P95 更慢 | [实现](../src/visiondata_gate/dynamic_benchmark.py) |
| DynamicBench-v2 | 调度对输入顺序和重复执行是否稳定 | 288 条记录符合冻结排序；24/24 输入顺序不变，24/24 重复回执稳定 | [实现](../src/visiondata_gate/dynamic_benchmark_v2.py) |
| DynamicBench-v3 | 冲突、新证据和故障下如何重规划 | 正确终态 8/8 对 4/8，调用 14 对 24，故障恢复 2/2 对 0/2 | [协议](../docs/DYNAMICBENCH_V3.md) · [冻结 JSON](DYNAMICBENCH_V3_REPLANNING_20260829.json) |
| DynamicBench-v4 | 基准是否进入真实产品内核 | 四类合成场景经过 ProductService、Incident、Control Plane 和 DecisionPacket | [协议](../docs/DYNAMICBENCH_V4.md) · [冻结 JSON](DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json) |
| IndustrialIncidentBench | 人工闸门、故障、预算与撤销如何处理 | 12 类本地 fixture 检验异常处置和权限停止路径 | [实现](../src/visiondata_gate/industrial_incident_benchmark.py) |
| Omni 授权离线试跑 | 数据整改与责任复验如何交接 | 49→33 findings；6 项关闭、43 项仍开放，转人工调查 | [历史记录](../docs/EVIDENCE_AND_BENCHMARKS.md) |
| Normality TTT 本地开发代理 | 单次真实参数更新能否在父模型不变时通过独立复验 | 3 步更新，16 图 TP/TN/FP/FN 保持 5/6/2/3；另一个全漏检基线在 0 步拒绝，**未观察到质量提升** | [脱敏摘要](NORMALITY_TTT_LOCAL_20260919.json) · [协议](../docs/NORMALITY_TTT.md) |

前三类 288 是各自协议的记录数，不是同一批独立工业样本。作者定义的合成基准用于工程/编排比较；Omni 记录与工厂独立真值评测是不同证据来源。原始私域图像和个人信息不在此分发。

## 复现

从仓库根目录，在锁定环境和新的输出目录运行：

```text
uv sync --locked --extra api --extra qa
uv run --no-sync visiondata-gate architecture-benchmark --output output/archbench-fresh.json
uv run --no-sync visiondata-gate dynamic-benchmark --output output/dynamicbench-v1-fresh.json
uv run --no-sync python tools/run_dynamic_benchmark_v3.py output/dynamicbench-v3-fresh.json
uv run --no-sync python tools/run_dynamic_benchmark_v4.py --output output/dynamicbench-v4-fresh.json --v3-report benchmarks/DYNAMICBENCH_V3_REPLANNING_20260829.json --scratch-root output/dynamicbench-v4-fresh-runtime
uv run --no-sync python tools/run_normality_ttt_synthetic.py
```

v3 的固定规则基线也保持不安全误放行为零；差异来自补证完整性、恢复和调用效率，不能写成固定基线误放行 4/4。单独的复杂冲突子集不并入这组分母。

v4 的“产品运行时”指真实软件调用链，不是工厂生产环境。重复运行会产生不同案件身份或计时，应核对协议、结果及完整性，不要求所有新 Run 的文件哈希与历史文件完全相同。

Normality TTT 的公开 JSON 是现有 VisA 开发代理的脱敏本地运行摘要，不含权重、原图或私人路径。合成 tensor 工具验证更新/回滚机制；真实 pack 摘要验证既有模型执行。二者都不是第三方复现、独立测试集或工厂效果证据。

## 结果应如何呈现

对每项实验列出验证问题、数据来源、基线、受控变量、指标分母、关键发现和运行产物。无原始回执或不可重跑的历史数字，标为历史记录而非本次复现。第三方 Agent 比较需使用实际运行记录，不能把下载代码或适配接口当作测评完成。
