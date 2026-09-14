# DynamicBench-v4：生产运行时桥接验证

DynamicBench-v4 只回答一个问题：冻结的本地合成案件是否真正经过
`ProductService → Incident v6 → Governed Audit Envelope → Control Plane →
DecisionPacket v3`，而不是由 benchmark 自己模拟 Planner、Tool、Council 或 Judge。

## 与 v3 的分工

- DynamicBench-v3：同输入、同工具结果、同预算的确定性固定规则/动态重规划对照；
- DynamicBench-v4：真实 ProductService 与 Incident v6 集成验证；
- 两者不得合并声称“生产环境动态策略优于固定规则”。

## 冻结场景

| 场景 | 目的 |
|---|---|
| P01 | 冲突证据触发真实动态 Worker 与 Council/Judge |
| P02 | 已资格化证据仍只到人工决定，不获得生产放行权 |
| P03 | 从 ProductService 注入生产 Worker Registry 故障并失败关闭 |
| P04 | 单 Worker 预算耗尽后阻断未评估证据 |

真值和期望仅存在于离线 fixture manifest；传给 ProductService 的
`IndustrialIncidentRequest` 不含 expected outcome、oracle 或 adjudication truth。

## 执行

```powershell
uv run --frozen python tools/run_dynamic_benchmark_v4.py
```

输出同时包含：

- 报告文件字节 SHA-256；
- 带域分隔、排除自哈希字段的 sealed report SHA-256；
- 每个真实 Incident v6、DecisionPacket v3、Control Plane 和 Audit Root 摘要；
- 明确的 `FROZEN_SYNTHETIC_FIXTURES / NOT_EVALUATED` 工业效果边界。
