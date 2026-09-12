# Governed Data Pool API v1

状态：`IMPLEMENTED_LOCAL / DTO_FROZEN_FOR_GOAL1_GOAL2 / NOT_RELEASED`。

该接口把单个已授权、已冻结的 Operator Project Snapshot 投影为逐成员审核池。它不判断
独立标签真值，不把“没有命中 finding”自动写成好数据，也不允许跨快照合并。所有业务
身份由宿主 FastAPI 的认证依赖提供；本模块不读取 `X-Actor-User-Id` 自行授权。

## 安装签名

```python
install_data_pool_routes(app, actor_dependency, product_dependency)
```

`actor_dependency` 返回宿主已经认证的实际账号；`product_dependency` 返回同一宿主的
`ProductService`。路由不建立 demo actor、启动 token 或第二套身份系统。

## 枚举

```text
member.disposition
  QUALIFIED_CANDIDATE
  REPAIR_REQUIRED
  UNVERIFIED_HOLD

member.repair_action
  NONE
  RELABEL
  RECAPTURE
  REMOVE_OR_REPARTITION
  INVESTIGATE

member.repair_result
  NOT_APPLICABLE
  PENDING
  EVIDENCE_LINKED_NOT_VERIFIED

projection.read_status
  CURRENT
  STALE_HOLD

derivation.materialization_mode
  FULL_SNAPSHOT_REFERENCE
  DERIVED_QUALIFIED_SUBSET

version.status
  REVIEWED_ALL_QUALIFIED_REFERENCE
  REVIEWED_ACTION_REQUIRED
  REVIEWED_WITH_HOLD
```

`QUALIFIED_CANDIDATE` 不是 `GOOD`，只表示当前成员在这一个冻结 Gate 的已映射证据下可
进入派生候选。所有成员固定 `label_truth_authority=false`。

## 创建初始 Pool

```http
POST /v1/tasks/{task_id}/data-pools
```

请求：

```json
{
  "request_key": "pool-create-0001",
  "expected_readiness_sha256": "<64 hex>",
  "reviewer_name": "named reviewer",
  "review_note": "reviewed every frozen member and its evidence",
  "operator_attests_reviewed": true,
  "members": [
    {
      "sample_id": "img_...",
      "expected_asset_sha256": "<64 hex>",
      "expected_annotation_revision": 3,
      "expected_annotation_sha256": "<64 hex>",
      "disposition": "QUALIFIED_CANDIDATE",
      "repair_action": "NONE",
      "repair_result": "NOT_APPLICABLE",
      "decision_note": "no member-level finding remains in this frozen evidence"
    }
  ]
}
```

`members` 必须精确覆盖历史 Snapshot 的全部成员。服务端重新读取历史 task、source、
snapshot、manifest、contract、Gate 与 `learning_readiness`，并核对图片 SHA、annotation
revision/document SHA。客户端不提交文件路径、finding code 或数据源根目录。

响应 `201`：`DataPoolProjectionV1`。

## Pool 版本

```http
POST /v1/data-pools/{pool_id}/versions
GET  /v1/data-pools/{pool_id}
GET  /v1/data-pool-versions/{version_id}
GET  /v1/tasks/{task_id}/data-pools
```

新版本请求在创建请求基础上增加：

```json
{
  "expected_pool_sha256": "<current pool receipt>",
  "expected_parent_version_sha256": "<current version receipt>",
  "source_task_id": "<optional newly rechecked task; defaults to parent source task>"
}
```

每个版本保留 `parent_version_id/sha256`；旧版本不可更新或删除。`source_task_id`
允许把修复后的同 workspace/project 新 Snapshot + 新 Gate 作为下一版本的完整成员来源；
成员不会与父版本做跨快照 union。Pool 保留 origin，并更新 current binding。

`DataPoolProjectionV1`：

```json
{
  "schema_version": "visiondata-gate.data-pool-projection.v1",
  "pool": {
    "schema_version": "visiondata-gate.data-pool.v1",
    "pool_id": "pool_...",
    "workspace_id": "wsp_...",
    "project_id": "prj_...",
    "origin_task_id": "tsk_...",
    "current_task_id": "tsk_...",
    "origin_source_id": "src_...",
    "current_source_id": "src_...",
    "origin_snapshot_id": "opsnap_...",
    "current_snapshot_id": "opsnap_...",
    "version_ids": ["poolv_..."],
    "current_version_id": "poolv_...",
    "created_by": "authenticated actor",
    "created_at": "ISO-8601 local record time",
    "label_truth_authority": false,
    "production_release_allowed": false,
    "receipt_sha256": "<64 hex>"
  },
  "current_version": {
    "schema_version": "visiondata-gate.data-pool-version.v1",
    "version_id": "poolv_...",
    "pool_id": "pool_...",
    "version_number": 1,
    "parent_version_id": null,
    "parent_version_sha256": null,
    "source_task_id": "tsk_...",
    "workspace_id": "wsp_...",
    "project_id": "prj_...",
    "source_id": "src_...",
    "snapshot_id": "opsnap_...",
    "snapshot_receipt_sha256": "<64 hex>",
    "batch_manifest_sha256": "<64 hex>",
    "batch_contract_sha256": "<64 hex>",
    "gate_result_sha256": "<64 hex>",
    "readiness_receipt_sha256": "<64 hex>",
    "preflight_receipt_sha256": "<64 hex or null>",
    "status": "REVIEWED_ALL_QUALIFIED_REFERENCE",
    "qualified_count": 1,
    "repair_count": 0,
    "hold_count": 0,
    "members": ["<server-enriched member ledger>"],
    "global_finding_refs": [],
    "unmapped_finding_refs": [],
    "readiness_blockers": [],
    "human_review": {
      "reviewer_name": "named reviewer",
      "review_note": "...",
      "reviewed_by": "authenticated actor",
      "operator_attests_reviewed": true
    },
    "label_truth_authority": false,
    "training_ingestion_allowed": false,
    "production_release_allowed": false,
    "receipt_sha256": "<64 hex>"
  },
  "read_status": "CURRENT",
  "stale_reasons": [],
  "training_ingestion_allowed": false,
  "production_release_allowed": false,
  "receipt_sha256": "<64 hex>"
}
```

服务端成员 ledger 额外包含真实 `split/category/annotation_requirement/readiness_state`、
`finding_refs`、从 finding 推导的 `repair_cause_codes` 和人工记录的 action/result/note。

成员完整 key 为：

```text
sample_id, source_task_id, split, category, annotation_requirement,
readiness_state, asset_sha256, annotation_revision, annotation_sha256,
mask_sha256, finding_refs, repair_cause_codes, disposition, repair_action,
repair_result, decision_note, label_truth_authority
```

`GET /v1/data-pool-versions/{version_id}` 返回
`visiondata-gate.data-pool-version-projection.v1`，形状为
`{version,read_status,stale_reasons,training_ingestion_allowed,production_release_allowed,receipt_sha256}`，
不是裸 version。

Task list 返回 `visiondata-gate.data-pool-list.v1`：
`{task_id,workspace_id,project_id,items,receipt_sha256}`，其中 `items` 是完整 pool
projection。

## 派生合格候选

```http
POST /v1/data-pools/{pool_id}/versions/{version_id}/derive
```

请求：

```json
{
  "request_key": "pool-derive-0001",
  "expected_pool_sha256": "<current pool receipt>",
  "expected_version_sha256": "<current version receipt>",
  "review_note": "derive reviewed qualified candidates only",
  "operator_attests_reviewed": true
}
```

响应：

```json
{
  "schema_version": "visiondata-gate.data-pool-derivation.v1",
  "derivation_id": "poold_...",
  "pool_id": "pool_...",
  "version_id": "poolv_...",
  "workspace_id": "wsp_...",
  "project_id": "prj_...",
  "source_task_id": "tsk_...",
  "qualified_sample_ids": ["img_..."],
  "excluded_sample_ids": ["img_..."],
  "materialization_mode": "DERIVED_QUALIFIED_SUBSET",
  "parent_source_id": "src_...",
  "derived_source_id": "src_...",
  "derived_snapshot_id": "opsnap_...",
  "derived_snapshot_receipt_sha256": "<64 hex>",
  "new_source_authorization_created": true,
  "new_gate_required": true,
  "plan_approval_required": true,
  "new_gate_status": "NOT_STARTED",
  "source_authorization_status": "ACTIVE",
  "created_by": "authenticated actor",
  "created_at": "ISO-8601 local record time",
  "human_review_note": "...",
  "training_ingestion_allowed": false,
  "label_truth_authority": false,
  "production_release_allowed": false,
  "receipt_sha256": "<64 hex>"
}
```

若所有成员均为 qualified，不制造一份伪“新数据”：返回
`FULL_SNAPSHOT_REFERENCE`、`derived_source_id=null`、
`derived_snapshot_receipt_sha256=null`、`new_source_authorization_created=false`、
`new_gate_required=false`、`plan_approval_required=false`、
`new_gate_status=NOT_APPLICABLE`。原 task/Gate 仍是引用，后续训练仍需独立明确授权。

若为真子集，服务端只调用受控 Snapshot subset materializer；创建新的只读来源授权，但
不自动创建新 Gate、启动任务、批准计划或送入训练。必须由后续人工动作创建新任务、完成
新 Gate 与计划审批，才能成为新的完整学习输入。

## 幂等对账

```http
GET /v1/projects/{project_id}/data-pool-operations/{operation}/{request_key}
  ?target_id={task_id|pool_id|version_id}
```

`operation=create|version|derive`。命中返回当前已验证结果；未命中返回：

```json
{
  "schema_version": "visiondata-gate.data-pool-operation.v1",
  "project_id": "prj_...",
  "operation": "create",
  "target_id": "tsk_...",
  "request_key": "pool-api-missing-001",
  "lookup_status": "NOT_FOUND",
  "execution_status": "UNKNOWN_NOT_PROOF_OF_NO_WRITE",
  "result_type": null,
  "result_id": null,
  "current_result": null,
  "result_semantics": "CURRENT_RESULT",
  "automatic_retry_allowed": false,
  "receipt_sha256": "<64 hex>"
}
```

相同作用域、operation、target 和 request key 但请求内容不同返回 `409 data_pool_hold`。

## Fail-closed 规则

- `global_findings`、`unmapped_finding_refs`、工具失败、缺工具、快照/标注身份不完整或
  readiness 未验证时，任何成员都不能标 `QUALIFIED_CANDIDATE`；
- 仅批次因其他**已映射到成员**的 finding 被阻断时，没有成员 finding 的补集才可作为
  qualified candidate；该分支还要求 `preflight_eligibility=HOLD`、blockers 精确为
  `[GATE_NOT_PASS]`，并且至少另一成员存在真实 mapped finding；它仍不是独立标签真值；
- `MASK_REQUIRED_FOR_REFERENCE_TRAINER` 不是坏数据。仅当原 Gate 为 PASS、工具与 finding
  映射完整、成员无 finding、要求为 OPTIONAL/NOT_APPLICABLE，且空标注 revision/SHA 与
  Snapshot 完全一致时可进入候选；后续检测数据桥仍需独立具名无目标声明；
- 当前 annotation revision 或 SHA 与历史 Snapshot 不同，拒绝并要求新 Snapshot/Task；
- Source 撤权或过期时拒绝读取和派生；Evidence 漂移返回 `STALE_HOLD`；
- 任何响应固定 `training_ingestion_allowed=false`、`label_truth_authority=false`、
  `production_release_allowed=false`；
- API 不接受任意服务器文件路径；
- 数据池不自动混入 val/test、不自动关闭 CAPA、不启动模型训练。

## 下游服务端读取 Helper

模型/检测数据桥不能直接读取 SQLite 或目录，必须调用：

```python
load_fresh_data_pool_context(
    product,
    actor,
    pool_id,
    version_id=None,
    require_current=True,
    require_all_qualified=True,
    require_gate_pass=True,
)
```

返回 `FreshDataPoolContext(pool,version,task,source_root,snapshot,manifest,contract,gate,readiness)`。
模型数据桥使用三个严格开关；因此 proper subset 的 `new_gate_status=NOT_STARTED` 不能直接
进入模型。用户必须为新来源创建 task、人工批准计划、完成新 Gate，再通过
`CreateDataPoolVersionRequest.source_task_id` 形成下一版本，Helper 才允许继续。
