# 异常检测 Operating Point 治理合同

## 当前状态

`src/visiondata_gate/anomaly_operating_point.py` 是一个已经有专项测试的**源码级诊断组件**，用于在冻结的异常分数上选择可复算的 score channel 与 threshold，并在独立的留出开发分割上评估该选择。

```text
implementation_status=SOURCE_COMPONENT_TESTED
product_connection_status=PRODUCT_API_NOT_CONNECTED
fresh_external_run=NOT_RUN
industrial_threshold_validation=NOT_RUN
production_release_allowed=false
```

它没有接入当前产品 API、Web 工作台或自动生产放行链，也不把开发集阈值称为工厂阈值。现有工具脚本只读取用户明确指定的本地运行目录并生成诊断回执；产物不会自动进入 Git、Release 或公共 Demo。

## 为什么要单独治理阈值

异常检测模型通常同时给出全图均值、局部 Top-K 聚合和最大响应等分数。小缺陷可能被全图均值稀释，因此“选哪个分数通道”和“阈值是多少”必须一起冻结，并与训练和最终测试分开。

本组件把样本分成两个明确角色：

- `calibration`：只用于选择分数通道与阈值；
- `heldout_development`：只用于检查该选择是否在未参与选择的开发样本上仍满足目标。

两个分割的 `source_sample_id` 必须互斥。每个分割必须同时包含 `normal` 与 `anomaly`，分数通道集合必须一致，非有限数值、重复样本、未知标签或分割角色漂移都会失败关闭。

## 确定性选择规则

对每个分数通道枚举全部唯一观测阈值以及“高于最大分数”的边界点，先过滤掉超过 `max_false_positive_rate` 的候选，再按以下固定顺序选择：

1. 最大 Recall；
2. 最小 False Positive Rate；
3. 最大 F1；
4. 更高阈值；
5. 通道名的确定性字典序 tie-break。

输出同时包含 TP、FP、TN、FN、分母、Accuracy、Recall、FNR、FPR、Precision、F1 与 Recall/FPR 的 Wilson 95% 区间。区间用于描述当前有限样本的不确定性，不是总体性能保证。

即使 calibration 达到目标，输出仍保持：

```text
deployable_threshold=null
independent_evaluation_required=true
production_release_allowed=false
machine_write_permitted=false
```

只有 `heldout_development` 也满足冻结目标时，状态才可成为 `TARGET_MET_PENDING_INDEPENDENT_REVIEW`；这仍不是 fresh test、客户验收或生产批准。

## 输入最小合同

每条记录必须包含：

```json
{
  "source_sample_id": "stable-sample-id",
  "split_role": "calibration",
  "product_label": "normal",
  "image_scores": {
    "mean": 0.12,
    "top_0_1pct": 0.63
  }
}
```

`summarize_anomaly_map()` 可从二维有限数值异常图生成 mean、max 与多个局部 Top-K 均值通道；它不读取或生成参考 Mask，也不授权自动改标。

## 本地诊断入口

- `tools/audit_anomaly_operating_points.py`：对已有冻结逐样本分数做回顾性 operating-point 审计，不重新训练、不修改权重；
- `tools/rescore_anomaly_channels.py`：在明确提供的可信本地 Normality pack 上复算多个分数通道，禁用网络与子进程，并把 `fresh_test_validation` 保持为 `NOT_RUN`。

示例命令仅适用于拥有相应本地私有运行目录的操作者：

```text
python tools/audit_anomaly_operating_points.py \
  --run <LOCAL_RUN_ROOT> \
  --output <NEW_LOCAL_OUTPUT_JSON> \
  --min-recall 0.80 \
  --max-fpr 0.20
```

本地运行目录可能包含不可公开的数据路径和样本身份；输出发布前必须单独完成隐私、许可、分母与哈希审查。

## 可复现检查

```text
python -m pytest tests/test_anomaly_operating_point.py -q
```

专项测试覆盖通道联合选择、相同分数不可伪造召回率、校准/评估重叠拒绝、回执漂移、NaN/Inf/bool、单类别分母、通道集合漂移、小缺陷局部分数、评估失败保持 HOLD，以及排序扫描与穷举阈值的一致性。
