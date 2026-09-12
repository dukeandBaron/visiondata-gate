# 已验收数据池到本地检测数据集

本适配器把当前完整、全部成员已审核合格且来源 Gate 为 PASS 的数据池版本，转换为显式检测框数据集。它复用数据池生产服务的实时校验入口，不接受客户端提交服务器路径，也不从二值 mask 生成检测框。

## HTTP 入口

`POST /v1/projects/{project_id}/vision-datasets/from-data-pool`

成功返回 `201`。接口复用主应用登录身份，并要求连接对端为 loopback IP。请求 DTO 是 `RegisterPoolDetectionDataset`：

| 字段 | 内容 |
|---|---|
| `request_key` | 本次登记的幂等键；相同键必须保持请求内容一致 |
| `reviewer_identity`、`note` | 本次登记的具名审核者及说明 |
| `pool_id`、`version_id` | 数据池及当前版本 ID |
| `expected_pool_receipt_sha256` | 当前 pool 记录的回执摘要 |
| `expected_version_receipt_sha256` | 当前 version 记录的回执摘要 |
| `class_names` | 显式类别顺序；类别集合必须与冻结来源词表相同 |
| `groups` | 每个冻结样本 ID 对应的独立分组；必须精确覆盖全部成员 |
| `normal_sample_ids` | 明确声明为空框正常样本的 ID；默认空列表 |
| `operator_attests_data_authorized` | 必须为 `true`，确认授权本次数据转换 |

类别在 `class_names` 中的位置就是检测标签的 `class_id`。重排会生成不同的映射摘要；引入未审核类别、缺少框标签所属类别或重复类别都会拒绝。

响应为与其他视觉数据集相同的已校验回执，含 `dataset_id`、`dataset_receipt_sha256` 和 `pool_binding`，附 `ETag`、`X-Content-SHA256` 以及 `Cache-Control: private, no-store`。私有源目录仅保存在服务内部。

可通过以下接口恢复记录，无需重复执行转换：

```text
GET /v1/projects/{project_id}/vision-datasets
GET /v1/projects/{project_id}/vision-operations/register_pool_dataset/{request_key}
```

## 输入验证

适配器调用 `load_fresh_data_pool_context(..., require_current=True, require_all_qualified=True, require_gate_pass=True)`，以生产服务当前结果为准。绑定使用 pool 的 `current_task_id/current_source_id/current_snapshot_id`，以及 version 的 `source_task_id`；不把历史 `origin_*` 当成当前来源。

接受输入还需同时满足：

- 来源任务完成，冻结 Gate 为 PASS，必需工具齐全且无错误；没有全局、未映射或成员 finding，没有 readiness blocker。
- 当前数据池版本的所有成员均为 `QUALIFIED_CANDIDATE`；成员、冻结快照、来源 manifest、审核要求和 `groups` 的样本集合完全一致。
- 通过宿主的冻结快照上下文解析来源，并逐项核验 source、snapshot、manifest、contract、Gate、readiness 的身份和摘要。
- 使用快照记录的 actor 和 workspace 从 `OperatorImageStore` 读取实时框；图片摘要、标注 revision、标注文档 SHA 与冻结快照及人审记录一致。
- 原图尺寸匹配记录，只接受单帧和 EXIF 方向为 1 的图像，防止把转正预览上的框直接套到不同方向的原始字节。
- 正常样本必须没有框，冻结标注策略为 `OPTIONAL` 或 `NOT_APPLICABLE`，且 `normal_sample_ids` 精确覆盖所有空框成员。框样本不能同时声明正常。
- 继续执行检测数据集模块的 train/val/test、类别、分组、内容隔离和资源预算检查。

编辑器中的框采用归一化左上角 `x, y, width, height`。转换只计算 `x_center=x+width/2`、`y_center=y+height/2`，保留宽高；原始图片字节保持不变。来源、类别顺序、坐标约定、每个样本的标注和尺寸均进入绑定摘要。

派生子集的 `new_gate_status=NOT_STARTED` 不能作为该接口输入。它必须先取得与新来源匹配的真实完成任务、PASS Gate 和当前全员合格审核版本。

当前数据池生产规则允许受严格证据约束的成员级合格候选补集：readiness 必须为 `VERIFIED`，没有全局、未映射或工具错误阻断，候选成员没有自己的 finding，且批次唯一 blocker 为 `GATE_NOT_PASS` 时，`BLOCKED_BY_BATCH` 成员可以经人审标为 `QUALIFIED_CANDIDATE`。例如一张真实暗图使批次 Gate 未通过，而其余四张图片满足上述条件时，可形成 `4 qualified / 0 hold / 1 repair` 的审核池。这个成员级候选资格不授予训练权；本适配器仍同时要求完整 Gate PASS 和全部成员合格，因此拒绝该池直接进入训练。

## 再验证与提交

实现位于 [vision_data_pool_bridge.py](../src/visiondata_gate/vision_data_pool_bridge.py)，提供三个入口：

```python
pool_detection_input(product, actor, project, request) -> tuple[Path, dict, dict]
verify_pool_binding(product, actor, project, binding) -> None
verify_pool_binding_in_connection(connection, actor, project, binding) -> None
```

第一项返回私有来源根目录、显式检测 manifest、可公开给当前项目成员的绑定。第二项重新读取当前生产服务、冻结证据与实时框，用于登记、启动、结果发布及人工选模前的完整复验。

第三项应在完整复验之后、保存结果之前，由调用者在已经开始的写事务中使用。它只执行 SELECT，检查 ACTIVE 账号、项目成员关系、数据池当前版本、任务状态与证据摘要、来源授权及到期时间；不创建表、不另开连接、不提交事务，也不代替图片和标注文件复验。这个拆分避免了在写事务内部触发生产服务建表或另开连接造成的锁等待，并使数据库内的撤权及版本切换能在同一事务中被拒绝。

完成数据集登记不会启动训练。数据池和转换回执都不构成独立标签真值或生产批准；训练仍需独立的具名授权，候选模型仍需人工选择。

## 本地验证记录（2026-09-13）

[视觉 API 专项](../tests/test_vision_model_api.py) 完整运行 `50 passed`，包括主应用实际挂载后的会话校验、pool 转换入口，以及反馈查询和人工分类路由的认证、loopback 与 OpenAPI 合同。

[数据池桥接专项](../tests/test_vision_data_pool_bridge.py) 历史完整运行得到 `24 passed / 1 failed`，该失败对应数据池资格规则尚在调整的暗图负例。生产规则最终恢复受严格证据约束的成员级候选补集后，该用例已改为创建真实 `4 qualified / 0 hold / 1 repair` 池，并分别验证完整 Gate 要求与训练桥接的拒绝行为。最新单项复验结果为 **`1 passed`，35.68 秒**；本轮未重新执行整套桥接用例，不能将单项复验记录写成一次完整运行 `25 passed`。

桥接验证使用实际生成并上传的合成图片、审核框、冻结快照、真实 Gate 和真实数据池服务，没有伪造 PASS。覆盖实际 HTTP 201、幂等恢复、冻结标签字节、正常样本确认、标注和版本漂移、来源撤权，以及已有写事务内的版本切换和授权失效。静态检查和 Python 编译检查通过。

可复现命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_vision_model_api.py -q
.venv/Scripts/python.exe -m pytest tests/test_vision_data_pool_bridge.py -q
```

本轮执行的具体单项命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_vision_data_pool_bridge.py::test_real_nonpassing_gate_qualified_complement_is_not_a_training_dataset -q
```

这些用例证明本地输入转换与权限约束，不提供工业检测性能或企业收益结论。
