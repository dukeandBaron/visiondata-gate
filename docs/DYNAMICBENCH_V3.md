# DynamicBench-v3：动态重规划与固定规则流水线对照

## 结论边界

DynamicBench-v3 是独立新增的本地确定性编排基准，不替换 v1、v2，也不修改生产 Agent 内核迁就测试。

它只回答一个问题：在完全相同的合成输入、工具返回、最大工具预算和失败关闭规则下，动态重规划合同能否比冻结的固定规则流水线更完整地处理复杂冲突。

```text
能证明：冻结 fixture 上的编排路径、恢复能力、安全终态与工具开销
不能证明：真实工厂适用性、模型准确率、客户验收、生产 SLO 或竞品优劣
```

## 公平协议

固定分母为 8 个 fixture、2 种策略、16 条记录：

| 场景 | Fixture 数 | 验证内容 |
|---|---:|---|
| 冲突证据 | 2 | 冲突出现后是否进入裁决工具 |
| 工具失败 | 2 | 主工具失败后是否选择确定性 fallback |
| 不可判定 | 2 | 证据不足时是否保持 HOLD 并停止无效调用 |
| 新证据改变下一步 | 2 | 首轮证据出现后是否切换到新要求的工具 |

两种策略共享：

- 同一份 `initial_input`；
- 同一份 `tool_result_mapping`；
- 每 fixture 最多 3 次工具调用；
- 同一个终态裁决器；
- 缺证、冲突、不可判定全部失败关闭为 `HOLD`；
- 外部模型调用、Token 与供应商费用均为 0。

固定规则基线冻结调用顺序：

```text
metadata_reconciliation
→ annotation_integrity
→ cross_tool_conflict_adjudication
```

动态策略根据刚取得的证据选择下一工具；发生路径变化时，复用生产公开合同：

- `build_case_evidence_belief_ledger_v2`
- `build_evidence_belief_revision_receipt_v1`
- `verify_evidence_belief_revision_receipt_v1`

每次重规划必须封存 `fresh_replan_required=true` 的 revision receipt。Benchmark 调用这些合同作为被测对象，不反向修改它们。

## 当前冻结结果

| 指标 | 固定规则基线 | 动态重规划合同 |
|---|---:|---:|
| 正确终态 | 4 / 8 | 8 / 8 |
| 不安全误放行 | 0 / 8 | 0 / 8 |
| 必要证据覆盖 | 6 / 12 | 10 / 12 |
| 工具调用总数 | 24 | 14 |
| 非必要工具调用 | 14 | 0 |
| 工具失败恢复 | 0 / 2 | 2 / 2 |
| 新证据改变下一步适配 | 0 / 2 | 2 / 2 |
| 不可判定时正确 HOLD | 2 / 2 | 2 / 2 |
| 工具预算违规 | 0 | 0 |
| 生产重规划回执 | 0 | 6 |

不可判定 fixture 的必要证据本来就无法被解析，因此动态策略的必要证据覆盖是 `10 / 12`，不是为了形成漂亮数字而伪造为 `12 / 12`。

固定规则基线也保持 `unsafe_release=0`。它在无法补齐证据时返回 `HOLD`，而不是为了制造动态策略优势而错误放行；因此差异来自正确终态、恢复路径、证据覆盖和冗余调用，不来自放宽安全红线。

## 防篡改与重放

报告采用 RFC 8785 JCS 和显式域分离、长度前缀的 SHA-256 framing：

```text
magic
+ uint32_be(domain_utf8_length)
+ domain_utf8
+ uint64_be(jcs_payload_length)
+ RFC8785_JCS(payload)
```

协议、fixture manifest、record、records、metrics、comparisons 和 sealed report 使用不同域。SHA-256 只用于未加密的篡改检测，不是数字签名、可信时间戳、身份凭证或授权证明。

加载验证器会：

1. 验证所有顶层 framed SHA 和每条 record SHA；
2. 对照代码内冻结协议与 8 个 fixture；
3. 检查完整的 `2 strategy × 8 fixture` 网格；
4. 重放每条策略并逐 JCS 字节比较 record；
5. 重新计算 metrics、comparisons 与状态；
6. 验证每份 belief ledger 与 revision receipt；
7. 拒绝修改内容后自行重算 SHA 的协议、fixture、record 或指标。

## 运行

```powershell
uv run python tools/run_dynamic_benchmark_v3.py 10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json
```

聚焦验证：

```powershell
uv run pytest -q tests/test_dynamic_benchmark_v3.py
uv run ruff check src/visiondata_gate/dynamic_benchmark_v3.py tests/test_dynamic_benchmark_v3.py tools/run_dynamic_benchmark_v3.py
```
