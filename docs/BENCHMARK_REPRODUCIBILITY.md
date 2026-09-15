# 基准与安全评估复现边界

状态快照：2026-09-12。本文把完整 DynamicBench-v3、轻量复现子集、外部 Agent
对照和 prompt-injection 固定集分开，避免不同分母互借结论。

## 1. DynamicBench-v3 完整协议

完整机器可读报告：

```text
benchmarks/DYNAMICBENCH_V3_REPLANNING_20260829.json
文件 SHA-256  424be5fc8f51d55bf412b6e73c88a4943bc2d403b1e2d85817b7eb7de9e36d21
Report seal     6a2b107c20eac5f590d9e36a9bcdb835efd080dc9c456528d18e224831585455
```

固定参数：

| 参数 | 值 |
|---|---|
| 数据 | 8 个作者定义的冻结合成 fixture |
| 场景 | 冲突、工具失败、不可判定、新证据改变下一步，各 2 个 |
| 策略 | `fixed_rule_baseline`、`dynamic_replanning_contract` |
| 原始记录 | `2 x 8 = 16` |
| 单 fixture 工具预算 | 3 |
| 初始输入 | 两种策略共享 |
| 工具结果映射 | 两种策略共享 |
| 终态裁决器 | 两种策略共享、失败关闭 |
| 随机 seed | `NOT_APPLICABLE`；fixture 与执行顺序为代码冻结常量 |
| 模型 / 温度 | `NOT_CONNECTED / NOT_APPLICABLE` |
| 外部模型调用 | 0 |
| 工业效果 | `NOT_EVALUATED` |

完整结果仍是：Dynamic 正确终态 `8/8`、Fixed `4/8`，工具调用 `14 vs 24`，
Dynamic 工具故障恢复 `2/2`，两者不安全误放行均为 `0/8`。这些数字只说明当前
作者定义合成协议上的编排差异。

fresh clone 环境与完整重放：

```bash
uv sync --extra qa --locked
uv run --no-sync python tools/run_dynamic_benchmark_v3.py \
  output/reproducibility/DYNAMICBENCH_V3_FULL_REBUILT.json

uv run --no-sync pytest -q tests/test_dynamic_benchmark_v3.py
```

加载器会验证固定协议、fixture、完整策略网格、每条 record、指标和 belief revision
回执，并从代码重新执行两种策略。它不是只检查保存文件中的摘要。复现命令写入新的
`output/reproducibility/` 路径，不覆盖冻结的 `10_reports/` 原始证据。

## 2. 四场景轻量复现子集

为了让第三方快速检查原始 record，仓库提供一个确定性投影入口：

```bash
uv run --no-sync python tools/run_dynamic_benchmark_v3_subset.py \
  examples/reproducibility/DYNAMICBENCH_V3_REPRO_SUBSET.json

uv run --no-sync python tools/run_dynamic_benchmark_v3_subset.py \
  examples/reproducibility/DYNAMICBENCH_V3_REPRO_SUBSET.json --verify-only
```

该入口会先：

1. 完整加载并重放验证 8-fixture 报告；
2. 从当前源码重新构建并自验证完整报告，不依赖 `10_reports/` 私有发布目录；
3. 使用冻结 `balanced-smoke-a-v1`：`C01 / F02 / I01 / N02`；
4. 导出两种策略的 8 条未经汇总替代的原始 record；
5. 绑定生成的完整报告、协议、fixture manifest、records 和源模块文件 SHA-256；
6. 不写运行时间戳，保证相同输入产生相同字节。

默认 profile 同时平衡：

- 入口工具：`metadata_reconciliation=2`、`annotation_integrity=2`；
- 期望终态：`RELEASE=1`、`HOLD=1`、`BLOCK=2`；
- 每个冻结场景类恰好一条。

另提供互补冻结 profile `balanced-smoke-b-v1`。任意 `--fixture-id` 自选组合即使覆盖
四个场景，也只能输出 `CUSTOM_SELECTION_NOT_COMPARABLE`，不能继承公开 PASS 标签。
如本地同时持有冻结完整报告，可额外传入 `--full-report`，要求源码重建对象与该报告
JCS 字节完全一致。

当前子集：

```text
Artifact file SHA-256  ddc4a853260844150e9ce18e96ee44bfb72863d581d6f0e68aca55f6cdaf0776
Subset payload SHA-256 f3619e0e7410bafeef9fc2f857ebe3b2a98ba8e786f3e57291f3004bf7fa98c4
Fixtures                  4
Raw records               8
Fixed correct             2/4
Dynamic correct           4/4
Tool calls                12 vs 7
Unnecessary calls         7 vs 0
Failure recovery          0/1 vs 1/1
Unsafe release            0 vs 0
```

这个子集是复现便利入口，不是新的统计显著性证据，也不能替代完整 8-fixture 报告。

专项测试：

```bash
uv run --no-sync pytest -q tests/test_dynamic_benchmark_v3_subset.py
```

## 3. 自评偏差与未执行对照

必须同时披露：

- fixture、必要证据、期望终态以及两种策略均由项目作者定义；
- 固定基线是冻结的三工具流水线，不是 ReAct、LangGraph 或第三方 Agent；
- `ReAct/LangGraph external baseline = NOT_RUN`；不得根据当前数字推断其表现；
- 8 个合成 fixture 太小，不能估计真实工厂的误放行率、误拦截率或尾部故障；
- 0 模型调用意味着该基准评估确定性编排合同，不评估 LLM 推理质量；
- 当前 VisA 代理、私域 Omni Pilot 和 DynamicBench-v3 是不同评价平面；公开 VisA
  代理能否全量重跑，不改变 DynamicBench-v3 自身已经公开且可重放的事实。

若未来增加 ReAct/LangGraph 对照，必须先冻结相同输入、工具结果、预算、终态裁决器、
模型 ID、温度、seed、失败策略和原始 trace，再报告实跑结果。当前没有这些证据。

## 4. Prompt-injection 固定集

当前公开示例应引用 v2 回执，而不是保留用于历史对照的 v1 `8+5` 回执：

```text
examples/reproducibility/PROMPT_INJECTION_V2_FIXED_SET.json
文件 SHA-256  7db5fd3b906691e9938bc10b40a1a17e086dadaec625a45fe8d5b5f45526b03f
Schema          visiondata-gate.prompt-injection-evaluation.v2
Status          PASS_LOCAL_FIXED_ATTACK_SET
```

fresh clone 生成命令：

```bash
uv run --no-sync visiondata-gate prompt-injection-eval \
  --output examples/reproducibility/PROMPT_INJECTION_V2_FIXED_SET.json
```

当前固定分母结果：

| 指标 | 观察值 | 允许表述 |
|---|---:|---|
| 攻击拦截 | `12/12` | 固定攻击集观察拦截率 100% |
| 攻击漏拦 | `0/12` | 固定攻击集观察漏拦率 0% |
| 良性放行 | `6/6` | 固定良性集 utility 100% |
| 良性误伤 | `0/6` | 固定良性集观察误伤率 0% |
| 被阻断攻击的远程模型调用 | `0` | 预检在该固定集中实现 0-call 阻断 |

12 个攻击覆盖中英文指令覆盖、策略权限提升、秘密提取、工具描述投毒、角色冒充、
Base64、hex、URL 编码、嵌套 Base64、零宽字符和全角字符。6 个良性样本覆盖中英文
质量描述、工具结果、权限边界、模型限制和 URL 编码质量文本。

这些样本是项目作者编写的固定规则测试，不包含自适应攻击、模型生成攻击、图片/文件
多模态注入、无限层编码、tokenizer 特定后缀或真实红队统计。不得写成“普适注入防护”。

回执中的 `remote_model_calls_on_blocked_attacks=0` 是固定评估器输出字段，不是外部供应商
遥测。另一个集成测试验证命中规则后会在 HTTP 请求函数之前早退并得到 `model_calls=0`；
当前仍没有一份真实外部模型运行产生的持久化 `BLOCKED_LOCAL_RULESET` 产品回执。
