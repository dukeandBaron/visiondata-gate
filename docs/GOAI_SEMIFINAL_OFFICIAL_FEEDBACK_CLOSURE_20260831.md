# GOAI 复赛官方反馈闭环｜2026-08-31

> 本文件只记录可公开、可复核的反馈闭环状态。官方邮件原件、邮箱、联系人、私域路径、资产身份和原始回执均不进入仓库或发行包。

## 来源与时间边界

- 官方参赛手册 PDF 明文给出复赛阶段为 `8.25-9.3`，但未写 9 月 3 日的具体截止时刻。
- 后续官方复赛邮件确认提交截止时间为 **2026-09-03 18:00（北京时间）**。小时级口径来自该邮件，不应反写成“手册 PDF 已写明 18:00”。
- 项目内部封版线仍为 2026-09-02；它不是官方截止时间。
- 本文件不保存邮件截图或任何个人联系信息；平台上传仍须由账号持有人完成并保存作品 ID、提交时间、平台回执和实际上传文件 SHA-256。

## 官方两条优化反馈

| 官方反馈 | 当前闭环动作 | 当前证据边界 |
|---|---|---|
| 从公开数据集进一步走向真实工业数据的影子测试，验证实际生产环境适用性 | 已对经操作者声明授权的私域离线来源执行只读 Source Profile、固定 Gate、Parent → CAPA → Child Run 复验；公开材料只展示脱敏统计和状态 | 这是 operator-attested 的本地离线 Pilot，不是工厂在线 shadow test、独立权属认证、客户验收、生产部署或跨工厂泛化证明 |
| 公布误放行率、误拦截率及整改后通过率，并用复杂冲突案例展示动态重规划相对固定规则的优势 | 已把三类治理指标拆分为独立分子/分母；无真值的指标保持未测量；DynamicBench 比较合成编排，VisA RC5 正式复验比较合同感知恢复效率 | 私域 Pilot、公开工业代理与合成编排不得合并，也不得写成工厂准确率、客户效果或竞品实测结果 |

## 操作者声明授权的私域离线 Pilot 状态

公开材料只保留下列脱敏事实：

| 项目 | 当前状态 |
|---|---|
| Source Profile | `4,464 images / 1,439 masks`，只读画像；不等于 4,464 张全部执行 Policy Gate |
| 固定 Gate 批次 | `180 images / 60 masks` |
| Parent Gate | `RECAPTURE` |
| Child Gate | `RECAPTURE` |
| 整改后通过率 | `0/1`；Wilson 95% CI `[0%, 79.3%]` |
| 生产放行 | `production_release_allowed=false` |

`0/1` 的统计单位是一条已完成同合同 Child Run 的整改闭环：分子为通过复验的整改数，分母为已完成复验的整改数。它说明本轮整改未通过，不说明整改方案普遍无效，也不能外推为客户或工厂总体成功率。

私域原始图像、mask、类别名、文件名、来源路径、操作者身份和原始回执不进入公开包。公开统计不能反推出具体资产身份。

## 指标真值边界

当前没有可用于工厂级误放行/误拦截计算的独立双人复核或 QMS 真值。因此：

```text
false_release_rate=NOT_MEASURED_PENDING_ADJUDICATION
false_block_rate=NOT_MEASURED_PENDING_ADJUDICATION
post_remediation_pass_rate=0/1
```

不得把缺少真值时的 `0/0` 写成 `0%`，也不得用 finding 数、样本级异常检出、公开 benchmark 或 Agent 自身裁决代替独立真值。后续只有在真值清单、Gate 输出清单、作用域、授权事件和对应 SHA-256 全部绑定后，才可升级工厂级指标状态。

## VisA RC5 公开工业代理复验

2026-09-03 已在 RC5 当前环境完成 300 clean + 300 programmatic block 正式复验并返回 `PASS`：

| 指标 | Dynamic contract-aware | Fixed uniform retry |
|---|---:|---:|
| Episodes | 600 | 600 |
| 正确终态 | 525/600 | 525/600 |
| Unsafe release | 0 | 0 |
| 瞬时故障恢复 | 150/150 | 150/150 |
| 工具调用 | 2,550 | 2,700 |
| 不可恢复故障冗余重试 | 0 | 150 |

- report semantic SHA-256：`1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c`；
- implementation receipt semantic SHA-256：`7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf`。

Dynamic 与 Fixed 正确终态相同，因此该运行不证明 Dynamic 更准确。它只证明程序化治理真值下的合同感知效率：在 unsafe release 同为 0 的前提下，Dynamic 避免了 150 次不可恢复故障冗余重试。它不证明 Worker replanning、工厂误放行/误拦截、自然缺陷检测精度、真实故障分布或客户 ROI；原始 VisA 字节与本机报告路径不公开。

## 动态重规划证据及分母隔离

当前有两组相关但分母不同的冻结合成证据，必须分开展示：

1. **DynamicBench-v3 主基准（8 fixtures）**：Dynamic 正确终态 `8/8`，Fixed `4/8`；工具调用 `14 vs 24`；Dynamic 工具故障恢复 `2/2`。该协议中两种策略均保持不安全误放行 `0/8`，差异来自正确终态、恢复路径、证据覆盖和冗余调用。
2. **冻结配对 episode 对照的复杂子集（4 episodes）**：在该报告定义的复杂证据冲突子集中，Fixed Rule 误放行 `4/4`，Dynamic `0/4`。该子集来自独立的配对治理协议，不能与上面的 8-fixture 分母合并。

两组结果都只证明冻结合成输入下的编排行为。外部模型调用和供应商费用均为 0；没有执行外部竞品系统。它们不证明真实工厂误放行率、误拦截率、模型准确率、客户 ROI、生产 SLO 或现场适用性。

## 当前提交裁决

```text
official_submission=PENDING
official_evaluation=NOT_EVALUATED
submission_eligible=false
production_release_allowed=false
```

本地材料完成或本地候选通过，均不能自动把上述状态升级。只有账号持有人完成官网上传并取得平台回执后，才能更新 `official_submission`；官方评审结果公布前，`official_evaluation` 必须保持 `NOT_EVALUATED`。

## 公开核验入口

- 评分证据索引：[`GOAI_SCORE_EVIDENCE_INDEX.md`](GOAI_SCORE_EVIDENCE_INDEX.md)
- 行业场景价值：[`INDUSTRY_SCENARIO_VALUE.md`](INDUSTRY_SCENARIO_VALUE.md)
- Evidence & Benchmarks：[`EVIDENCE_AND_BENCHMARKS.md`](EVIDENCE_AND_BENCHMARKS.md)
- DynamicBench-v3 协议：[`DYNAMICBENCH_V3.md`](DYNAMICBENCH_V3.md)

私域回执、内部报告和提交操作清单不从公共文档建立链接。
