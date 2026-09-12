# Goal 1 / learning backend integration contract

**接口字段已稳定（本轮 learning v1 开发收口）。** Root已完成真实隔离HTTP两轮，最终`output/learning-demo-http-04/LEARNING_DEMO_RECEIPT.json`状态`COMPLETED_REFERENCE_WORKFLOW`，最终cycle `FINALIZED`。下述normal/readiness/followup/operation/final-candidate字段均已在主工程实现；后续仅整理测试/文档，不主动改变字段，不修改Goal 1前端文件。源码与接口级验证不等同已打包、已上线或工业效果通过。

最终有界后端验收：三组不重叠测试154 + 22 + 41 = **217 passed / 0 failed / 0 skipped**；有已知Starlette弃用warning。原compute/snapshot/CAPA/API相关回归78 passed、8条已有warning。最终真实HTTP 75次请求、35.547秒、2轮实际训练，第二轮初始权重SHA与第一轮输出完全相同；逐样本readiness、反馈关联新Gate及精确成员、GET操作查询、显式反馈ID续轮均实际运行；最终test不回流逐样本任务，子进程正常exit0。最终合同/源码清单和请求Schema集中在`output/learning-backend-delivery-20260913-r2/`；manifest SHA为`d06d990b53a35d19cce59e16a0daecf9a777e3b2a2cffd4c24c556ebbc36ca11`。其中请求Schema摘要采用RFC8785 JCS内容规范化，不是pretty JSON文件字节摘要。更早214项快照与03记录保留为历史证据，不替代此结果；一次未产生JUnit的中断回归不计作通过。这不是全仓release回归结论。

本文说明学习闭环接口与历史开发验收范围。文中的本地运行回执不随公开源码分发，不能作为安装版或工业效果的独立公开证明。

## Ownership

- 学习后端任务拥有 `src/visiondata_gate/learning_{engine,dataset,evaluation,contracts,service,api}.py`、`tests/test_learning_*.py`、`tools/run_learning_demo.py`、本轮学习文档。`api.py` 本轮只在 `create_app` 尾部添加路由注册，保留所有原 dirty 内容。
- Goal 1 可负责前端状态展示、显式输入/组声明和数据处置到学习入口，以及其独立前端测试。不要复制训练服务、另建同名模型注册库，或覆盖上述后端文件。
- 前端或安装包尚未包含本轮新增学习功能的验收，不能把上一版桌面安装器当作学习闭环交付。

## 当前已有的逐样本清单

`GET /v1/learning-cycles/{cycle_id}` 返回 `dataset.samples`：`sample_id`, `split` (`train/val/test`), `category`, `group_id`, `image_path`, `mask_path`, `image_sha256`, `mask_sha256`, `pixel_sha256`, `mask_pixel_sha256`, `width`, `height`。图像路径是冻结学习副本内部相对路径，不是可公开下载URL；本接口不会提供原始私域图像URL。成员清单与`dataset_id`、`receipt_sha256`、原任务/来源/快照/Gate binding绑定。

这些字段不包含一个已经实现的通用 `GOOD/BAD/HARD/SHIFT` 标签。`category` 是任务类别，不能当质量状态；`split` 是用途划分；人工 `annotation_requirement` 来自既有输入快照要求，不能当作模型正确识别。样本GOOD/BAD处置面板应投影实际Gate findings/工单/复核结果；若需要独立质量分桶合同，先由前端列出展示需求，再由后端增加有依据的投影，不在UI制造通过状态。

当前只接受已通过真实`compute-preflight`、五工具齐全、显式v2人工复核的输入。参考训练器要求每个成员都有二值mask，并同时具备train/val/test；没有原mask的正常样本只能通过下面的显式正常声明生成学习副本mask，不能自动推断。数据/标注损坏、未明确要求、缺证据或工具失败不会成为可训练输入。

### 无缺陷负样本声明（已接后端并通过授权与混合训练验证）

CreateLearningCycle和RunLearningRound均新增可选`normal_mask_attestations`（默认空对象），键为实际sample_id；每项DTO：

```json
{
  "reviewer_name": "实际复核人姓名或标识",
  "review_note": "已查看这一冻结版本，明确确认不存在本次二值分割任务的目标前景",
  "expected_asset_sha256": "<该冻结图片SHA>",
  "expected_annotation_revision": 0,
  "expected_annotation_sha256": "<该冻结标注文档SHA>",
  "operator_attests_no_foreground": true
}
```

由实际snapshot.assets提供SHA/revision，不填占位值。后端先核对成员存在、原annotation_count=0、没有原mask，且三个预期身份值完全一致，再在学习副本生成全零PNG。不画假框，不修改operator_snapshot.py，不把空标注/NOT_APPLICABLE/模型预测自动当正常。已存在标注却声明正常、过期标注修订或摘要、未知成员会被拒绝。

学习dataset中非空声明入`normal_mask_attestations`；对应成员`mask_origin=EXPLICIT_HUMAN_ZERO_MASK`、`normal_attestation_sha256`，`mask_sha256`属于学习派生Mask，不冒充原标注。首次run应从cycle.request复用这份精确声明；续轮保留未变化成员声明，为新增正常成员另作声明。训练仍要求整体具有正负像素；全normal数据不应宣传成已训练出缺陷识别器。声明是具名人工证据，不是系统自动获得了独立语义真值。

## Create / run

`POST /v1/tasks/{task_id}/learning-cycles` (201)：

```json
{
  "request_key": "a-new-request-key",
  "expected_preflight_sha256": "<fresh compute-preflight receipt_sha256>",
  "groups": {"<every sample_id>": "<actual collection group declaration>"},
  "review_note": "明确同意本次本地CPU沙箱训练及预算",
  "operator_attests_training_authorized": true,
  "training": {"epochs": 250, "learning_rate": 1.5, "max_wall_seconds": 20.0},
  "evaluation": {},
  "max_rounds": 3,
  "max_total_epochs": 1000,
  "max_total_wall_seconds": 120
}
```

示例SHA占位不是有效请求。`groups` 必须精确覆盖数据成员，同一工件/采集组不能跨split；不能为了让校验通过给同一工件任意编造不同组。组名是操作者声明，不是系统已核实的工厂身份。

`POST /v1/learning-cycles/{cycle_id}/rounds`：`request_key`, `task_id`, `groups`, `expected_preflight_sha256`, `expected_cycle_sha256`, `review_note`, `operator_attests_training_authorized=true`，可选`responds_to_feedback_ids`（默认空）。第一轮使用初始冻结输入；后续完成轮必须提供新的训练数据，同时val/test指纹完全不变。FAILED/CANCELLED/INTERRUPTED后可显式新请求重试同一批准输入，不自动重放；失败尝试也占轮次/预算。

`responds_to_feedback_ids`现在只记录请求显式选择的反馈，不再自动关联全部上轮错误。非空时必须是上轮已复核反馈，且已通过下面的followup动作绑定本次相同的新Gate与实际训练成员；否则`FEEDBACK_ASSOCIATION_NOT_VERIFIED`。空数组允许与特定反馈无关的新授权数据训练，但不会产生“已回应所有问题”的声明。

本地接口复用既有交接前置检查，但不消费CANN资源假装运行NPU：原有`compute-handoffs`仍是`PREPARED_NOT_SUBMITTED`。训练接口明确运行NumPy CPU二值像素logistic参考模型，非RL、非已接通外部训练集群。

## Read / feedback / selection

| 入口 | 主要内容 |
| --- | --- |
| `GET /v1/projects/{project_id}/learning-cycles` | 当前有权限项目的周期列表 |
| `GET /v1/learning-cycles/{cycle_id}` | 周期状态、预算、数据清单、轮次ID、沙箱模型指针、事件、最终评测 |
| `GET /v1/learning-runs/{run_id}` | 真实训练配置/损失、模型/数据SHA、初始权重ID、验证结果与反馈项、选择记录 |
| `GET /v1/learning-models/{model_id}` | 核验文件SHA后的模型元数据和参考JSON权重；关联parent_model_id/run_id/dataset_id |
| `POST /v1/learning-cycles/{cycle_id}/runs/{run_id}/feedback/{feedback_id}` | 人工解释验证错误并登记下一步数据工作，不自动把验证样本放入训练 |
| `POST /v1/learning-cycles/{cycle_id}/runs/{run_id}/feedback/{feedback_id}/followup` | 把已分类反馈与新Gate证据和精确成员绑定，仍不自动判为已修复 |
| `POST /v1/learning-cycles/{cycle_id}/runs/{run_id}/selection` | `APPROVE_SANDBOX`或`REJECT`；仅当前ELIGIBLE候选可批准 |
| `POST /v1/learning-cycles/{cycle_id}/rollback` | 只回到本周期之前批准的模型，不能在待审核阶段偷换比较基准 |
| `POST /v1/learning-cycles/{cycle_id}/cancel` | 请求取消当前本地执行或停止待执行周期 |
| `POST /v1/learning-cycles/{cycle_id}/recover` | 超过执行租约后显式标记中断；不自动重放 |
| `POST /v1/learning-cycles/{cycle_id}/finalize` | 一次性消费test并结束周期；不返回test逐样本挖掘队列 |
| `GET /v1/tasks/{task_id}/learning-readiness` | 基于真实工具和Gate证据的逐样本处置投影，不把未知/失败归为好数据 |
| `GET /v1/projects/{project_id}/learning-operations/{operation}/{request_key}?target_id=...` | 对未知POST按作用域查询，GET不重放写入 |

所有人工动作带`request_key`, `expected_cycle_sha256`, `review_note`, `operator_attests_reviewed=true`。selection另带`expected_run_sha256`和action；rollback另带model_id；feedback另带classification，可选同项目`followup_task_id`。

followup DTO为上述人工字段加`expected_run_sha256`, `task_id`, `expected_preflight_sha256`, `sample_ids`（1..64唯一实际成员）。后端核对新task同项目、真实Gate可交接、与原来源不同、成员精确存在及其image/annotation/mask摘要，生成`feedback.followup`与`followup_status=NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED`。其中`issue_closed=false`与`training_ingestion_allowed=false`不改变；这是实际关联证据，不是自动证明模型错误已修复。旧`review_feedback.followup_task_id`单独出现时仍只是同项目关联声明，UI不可把它当已核验。

operation查询的operation为`create/train/feedback/select/rollback/cancel/recover/finalize/followup`。target_id：create用task_id，train/rollback/cancel/recover/finalize用cycle_id，feedback/followup用feedback_id，select用run_id。`lookup_status=FOUND`返回当前已核验结果及服务端验证后含默认值的请求SHA，`result_semantics=CURRENT_RESULT`；不是最初HTTP响应的逐字节副本。`NOT_FOUND`配`execution_status=UNKNOWN_NOT_PROOF_OF_NO_WRITE`，不能自动重新POST。身份与project一起过滤；`automatic_retry_allowed=false`固定。

readiness schema为`visiondata-gate.learning-readiness.v1`：`preflight_receipt_sha256`, `preflight_eligibility`, `blockers`, `projection_status`, `members`, `global_findings`, `unmapped_finding_refs`，成员含`sample_id/split/category/annotation_requirement/mask_available/readiness_state/finding_refs`。状态包括`UNVERIFIED_TOOL_FAILURE`, `UNVERIFIED_FINDING_IDENTITY`, `UNVERIFIED`, `NEEDS_ATTENTION`, `MASK_REQUIRED_FOR_REFERENCE_TRAINER`, `BLOCKED_BY_BATCH`, `GATE_ELIGIBLE_NOT_TRAINING_APPROVED`。缺mask不是坏数据；`training_authorized=false`固定，仍需二值mask/采集组/完整划分验证。

验证错误反馈项位于`run.feedback[]`，含feedback_id、evidence（sample/group/category及模型错误指标/摘要）、状态和下一步动作：

- 初始 `PENDING_HUMAN_REVIEW` + `INVESTIGATE`，不自动认定标签错误。
- 人工分类`HARD_SAMPLE` → `COLLECT_SIMILAR_TRAINING_EXAMPLES`。
- `DISTRIBUTION_SHIFT` → `RECAPTURE_REPRESENTATIVE_TRAINING_DATA`。
- `LABEL_ERROR` → `RELABEL_AND_NEW_EVALUATION_PROTOCOL`，周期HOLD，不偷偷更改固定验证真值。
- `INSUFFICIENT_EVIDENCE` → `INVESTIGATE`，周期HOLD。
- 复核后`TRIAGED_NOT_AUTO_INGESTED`，`training_ingestion_allowed=false`保持；“已分类”不等于“已完成整改”。下一轮run显式记录feedback_parent_run_id/responds_to_feedback_ids和新的数据binding，但不声称每条问题都已经消除。

## State and freshness rules

周期：`READY → RUNNING → AWAITING_REVIEW → AWAITING_DATA`；有界续轮重复中间阶段。最终测试使用`FINALIZING → FINALIZED`，失败或人工停止为`STOPPED`；真值/证据问题为`HOLD_REQUIRES_NEW_PROTOCOL`。run使用`RUNNING/COMPLETED/FAILED/CANCELLED/INTERRUPTED`。`COMPLETED`不是模型通过，必须看`evaluation.decision` (`ELIGIBLE/HOLD`)和blockers。

字典回执的`receipt_sha256`与强`ETag`、`X-Content-SHA256`绑定，no-store。每次feedback会改变run与cycle摘要；每次selection会改变cycle和run，所以提交后重新GET再执行下一步。列表保持原始list形状，无单独receipt。所有端点复用主API认证与项目membership，不自行信任浏览器传来的用户身份。

最终test会记录明确候选/比较基线与各自SHA；`FINALIZED`只表示一次性评测已经封存，不表示模型通过。如果候选未达到最终门槛，保留旧基线而不继续调这份test。同项目已消费的test像素/组不能通过新建周期再次进入训练或评测。

## Measurement boundary

评测是像素级TP/FP/TN/FN、Dice、像素漏检/误检率和逐类别回退检查，不是工件级漏检率或工厂KPI。分母为零保留None/HOLD。延迟为当前CPU单次观测，非正式性能基准。

所有选择都是沙箱选择，`production_release_allowed=false`, `remote_execution_verified=false`, `machine_write_permitted=false`。自动采集、真实模型后端、工业效果、生产IAM和全UI流程不因这些接口存在而宣称已完成。
