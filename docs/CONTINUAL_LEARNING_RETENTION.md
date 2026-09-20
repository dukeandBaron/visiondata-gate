# 持续学习候选的防遗忘评估合同

VisionData Gate 将持续学习定义为一个受控模型版本转换，而不是让生产权重在
测试流量上无限更新：

```text
只读 Parent Model
    ↓
新物件或新工况的 Candidate Model
    ↓
固定多物件 Retention Matrix
    ↓
Forgetting Gate
    ↓
ELIGIBLE_FOR_SANDBOX_REVIEW / HOLD_CATASTROPHIC_FORGETTING
    ↓
具名 APPROVE_SANDBOX_CONTINUAL / 保留父模型
```

本模块实现强类型 retention/forgetting **评估合同**、确定性计算、不可变本地
回执、认证 API 和候选模型选择硬门禁；它自身不执行训练。2026-09-19 新增的
[单次 Normality TTT](NORMALITY_TTT.md) 是另一条实际推理时参数更新路径：只改
克隆 student，结束重置，不能将其当作永久多物件持续学习。两条路径都不包含
在线设备控制，也不代表工厂影子测试或工业验收。

## 为什么不直接持续更新一个全局模型

持续 Test-Time Adaptation 会同时面临两类风险：

1. 学习新物件后破坏旧物件的特征与阈值，即灾难性遗忘；
2. 把未经确认的缺陷样本吸收到“正常”分布，导致异常分逐轮下降。

推荐的第一版执行结构是冻结共享 Backbone，并使用按物件或配方隔离的 Adapter、
Head、Prototype 或 Normality Model。需要跨物件合并时，在离线 Child Candidate
中使用授权 Replay、教师蒸馏和全量旧物件复验；父模型保持只读并可回滚。

## 合同必须绑定什么

`ContinualRetentionEvaluationRequest` 要求：

- 父模型 ID 与权重 SHA-256；
- 候选模型 ID 与权重 SHA-256；
- 固定 Backbone SHA-256；
- 固定 Retention Dataset 与成员清单 SHA-256；
- 独立评测器 SHA-256；
- 不重复的物件学习顺序；
- 每一阶段的模型 SHA、Backbone SHA、教师模型 SHA；
- 每一旧物件的 Replay 样本数与 Replay Manifest SHA；
- 每一阶段对所有已见物件的完整指标矩阵；
- 操作者对独立评测与 Replay 授权的显式声明。

缺少任一已见物件、未来物件提前进入矩阵、指标集合变化、非整数 Replay 数量、
Replay 低于下限、教师链断裂、Backbone 漂移或最终阶段未绑定候选权重时，请求在
计算前被拒绝。

## 指标与遗忘计算

对 higher-is-better 指标：

```text
forgetting(object) = max(history) - final
```

对 lower-is-better 指标：

```text
forgetting(object) = final - min(history)
```

负值统一截断为零。最终回执同时报告：

- 每个物件的学习阶段值、历史最好值、最终值与 observation count；
- 每个物件的 forgetting 与 backward transfer；
- 旧物件平均遗忘；
- 最坏物件遗忘与具体物件 ID；
- 所有物件的绝对最终指标门槛；
- 固定 prior-object denominator。

最后一个新物件没有经历后续任务，不进入平均遗忘分母，但仍必须通过绝对最终
指标门槛。

## Fail-Closed 裁决

任一条件成立即输出 `HOLD_CATASTROPHIC_FORGETTING`：

- 平均遗忘超过策略上限；
- 任一旧物件遗忘超过最坏物件上限；
- higher-is-better 最终值低于绝对下限；
- lower-is-better 最终值高于绝对上限。

只有没有 blocker 时才输出 `ELIGIBLE_FOR_SANDBOX_REVIEW`。即使通过：

```text
production_release_allowed=false
machine_write_permitted=false
industrial_acceptance=HOLD
```

## API

创建并保存一份绑定当前项目、父模型和候选模型的 Retention Receipt：

```http
POST /v1/projects/{project_id}/continual-retention/evaluations
```

重新读取并验证不可变回执：

```http
GET /v1/projects/{project_id}/continual-retention/evaluations/{receipt_sha256}
```

成功响应同时返回：

```text
ETag: "<receipt_sha256>"
X-Content-SHA256: <receipt_sha256>
Cache-Control: private, no-store
```

普通单物件候选仍可使用 `APPROVE_SANDBOX`。需要声明持续学习安全性的候选必须
使用：

```json
{
  "action": "APPROVE_SANDBOX_CONTINUAL",
  "expected_continual_retention_receipt_sha256": "<64-lowercase-hex>"
}
```

LearningService 会在同一选择事务提交前重新核对：

- 回执属于当前项目；
- 回执父模型等于 Run 初始模型；
- 回执候选模型等于 Run 产生的模型；
- 父子实际模型文件 SHA 与回执一致；
- 回执本身 JCS/SHA-256 自一致；
- `sandbox_promotion_eligible=true`；
- `production_release_allowed=false`。

遗忘 HOLD 回执、被替换的回执、跨项目回执或不匹配的模型 SHA 都不能改变
Champion Model。

## 建议的真实实验协议

当前测试只证明合同、计算、API、持久化和选择门禁工作。真实模型实验建议冻结：

```text
4 个物件
× 2～3 个学习顺序
× 3 个随机 seed
× 每阶段固定旧物件 Retention Set
```

至少报告 Image/Pixel AUROC、Image/Pixel F1、正常误报率、关键缺陷 Recall、
平均遗忘、最坏物件遗忘、Backward Transfer 和 P95 时延。阈值应在实验前写入策略，
不能看到结果后调整。

当前证据状态：

```text
CONTRACT_AND_API_IMPLEMENTED
SYNTHETIC_RETENTION_FIXTURES_PASS
REAL_MULTI_OBJECT_SEQUENCE=NOT_RUN
FACTORY_SHADOW_TEST=NOT_RUN
INDUSTRIAL_ACCEPTANCE=HOLD
PRODUCTION_RELEASE_ALLOWED=false
```
