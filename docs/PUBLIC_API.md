# VisionData Gate Python 公共 API 边界

状态快照：2026-09-12。本文只描述当前源码可验证的 Python 导入边界，不改变
HTTP、CLI、证据 Schema 或历史回放协议。

## 结论

当前包根的稳定面刻意保持最小：

```python
from visiondata_gate import GateDecision
```

`visiondata_gate.__all__ == ["GateDecision"]`，包版本为 `0.1.0`。只有包根
`__all__` 中的名称被声明为当前 0.1 系列的包级兼容入口。没有进入包根的模块并非
“不存在”或“不可用”，但调用方必须使用模块限定导入并绑定相应 Schema/协议版本。

```text
包根公开入口          package-level compatibility surface
模块 __all__          explicit module-scoped surface; pin its schema/protocol
下划线开头名称         internal implementation detail
HTTP / CLI / JSON      separate versioned contracts, not implied by Python __all__
```

本轮不扩大包根导出，也不搬移模块。仓库已经有大量模块限定消费者和冻结证据；在没有
迁移期、兼容测试和弃用窗口时重排目录，会破坏项目自己的可重放承诺。

## 版本化模块不是同一条“最新版替代旧版”链

| 模块 | 当前职责 | 新代码建议 | 兼容说明 |
|---|---|---|---|
| `dynamic_benchmark.py` | DynamicBench-v1：触发与四种编排策略的固定分母评测 | 仅在复现 v1 时使用 | 历史冻结协议；不是 v3 的旧实现 |
| `dynamic_benchmark_v2.py` | Worker 排序、预算、输入顺序不变性与重复稳定性 | Worker 选择评测使用 v2 | 与 v1/v3 回答不同问题 |
| `dynamic_benchmark_v3.py` | 固定流水线与动态重规划的 8 个合成 fixture 对照 | 编排对照使用 v3 | 不是外部 Agent 或工业效果基准 |
| `benchmarks/dynamic_benchmark_v4.py` | 真实 `ProductService -> Incident v6` 路径桥接 | 产品路径验证使用 v4 | v4 不继承 v3 的工厂效果结论 |
| `governance_effectiveness.py` | 当前产品 evaluation plane；同时承载 aggregate v1 与 per-unit manifest v2 | 新写入优先 v2 per-unit | FastAPI 与 `ProductService` 仍直接使用；v1 保留读写兼容 |
| `governance_effectiveness_v2.py` | 离线逐单元真值绑定、复赛 KPI 与 paired strategy 报告 | 评审证据构建使用 | 不替代产品 evaluation plane，不合并私域真值与合成指标 |
| `evidence_state.py` | v1 belief 视图，并兼容重导出 v2 合同 | 历史读取或兼容导入 | 仍是被支持的兼容层，不标记 deprecated |
| `evidence_state_contracts.py` | 无循环依赖的 v2 belief contracts | 新 Incident v6 工件优先使用 | 设计用于嵌入 Case canonical payload |
| `evidence.py` | 项目确定性 JSON、文件摘要与证据导出工具 | 项目内部工具使用 | `json.dumps(sort_keys=True)` 编码，不是 RFC 8785 JCS |

因此，以下说法不成立：

- “文件名带 `_v2` 或 `_v3`，此前模块就已经 deprecated”；
- “DynamicBench-v3 是 DynamicBench-v1 的结果升级”；
- “governance effectiveness v2 可以覆盖或重写 v1 历史回执”；
- “模块定义了 `__all__`，就等于包级语义版本承诺”。

## 调用方导入规则

### 包级稳定入口

```python
from visiondata_gate import GateDecision
```

### 模块限定、协议绑定入口

```python
from visiondata_gate.dynamic_benchmark_v3 import (
    build_dynamic_replanning_benchmark_report,
    validate_dynamic_replanning_benchmark_report,
)

from visiondata_gate.evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    verify_evidence_belief_ledger_v2,
)
```

调用方应同时检查输出的 `schema_version`、固定协议 ID 和验证函数；不要只依据 Python
函数名判断兼容性。

### 内部接口

任何以下划线开头的函数、常量或数据类均为内部实现。工具脚本为了构造仓库自有证据而
使用内部接口，不会自动把它提升为第三方稳定 API。

## 提升到包根公共 API 的门禁

新增包根导出前至少需要：

1. 明确的输入、输出和错误合同；
2. 独立 `schema_version` 或语义版本边界；
3. 正向、失败关闭、篡改和兼容测试；
4. 文档化导入路径与最小示例；
5. 至少一个弃用周期后才能删除旧入口；
6. 对冻结回执执行重放，证明历史字节没有被新导出改变。

当前没有执行大规模子包迁移，也没有对任何仍在使用的模块发出弃用声明。

本轮只做了两个不改变行为的 additive module export：

- `evidence_state_contracts.SourceAuthorizationStatusV2`：它已经出现在公开 builder
  的类型签名并被 Incident Kernel 跨模块使用；
- `benchmarks.dynamic_benchmark_v4.PRODUCTION_ROUTE`：它已经被只读 evaluation
  projection 跨模块使用。

二者没有进入包根 `visiondata_gate.__all__`，因此没有扩大包级稳定面。
