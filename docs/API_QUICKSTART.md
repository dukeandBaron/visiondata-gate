# VisionData Gate API 快速接入

VisionData Gate 提供一个真实本地 REST API。企业 Agent Demo、内部 SaaS 或数据流水线可以用同一个任务 ID 提交审核、查询状态、查看 trace 并下载 evidence。Streamlit 工作台与 API 共用 SQLite、`ProductService` 和原有 `run_agentic_demo`，不是两套演示逻辑。

## 1. 安装并启动

```powershell
uv sync --python 3.12.5 --extra ui --extra api --extra qa
.\run_api.ps1 -Port 8787
```

服务固定监听 `127.0.0.1`。启动后可访问：

- OpenAPI UI：`http://127.0.0.1:8787/docs`
- Schema：`http://127.0.0.1:8787/openapi.json`
- 健康状态：`http://127.0.0.1:8787/v1/health`

需要同时打开真实图片工作台时，可在仓库根目录执行 `.\run_workbench.ps1`，访问 `http://127.0.0.1:4173/workspace`。开发模式使用 `.\run_workbench.ps1 -Mode Dev` 和 `http://127.0.0.1:5173/workspace`。

## 2. 本地演示对象

工作台或默认 API 首次启动会原子创建一组固定的本地演示对象：

```text
user_id       usr_local_demo
workspace_id  wsp_local_demo
project_id    prj_industrial_vision
```

默认 API 不公开用户创建、用户枚举或工作区创建接口，避免把匿名本地引导误当成账户管理面。需要新增本地演示用户与工作区时，请在工作台“项目”页使用本地初始化入口；项目和审核任务可通过 API 创建。`X-Actor-User-Id` 只用于本地成员关系与逻辑作用域演示，不是登录认证、API Key 或生产 IAM。

### 2.1 真实图片 Operator API

IDE 式 `/workspace` 使用以下本地接口：

```http
GET  /v1/operator-workspaces/{workspace_id}/assets
POST /v1/operator-workspaces/{workspace_id}/assets
GET  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/content
GET  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/preview
GET  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/annotations
PUT  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/annotations
GET  /v1/operator-workspaces/{workspace_id}/work-orders
POST /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/work-orders
PUT  /v1/operator-workspaces/{workspace_id}/work-orders/{work_order_id}
GET  /v1/operator-workspaces/{workspace_id}/work-orders/{work_order_id}/crop
```

上传接口接收 `multipart/form-data` 的 `files` 字段，可一次提交多张 JPEG、PNG、BMP、TIFF 或 WebP。服务端校验解码、格式、单文件 32 MiB 和 5,000 万像素上限；保存原始字节、预览、像素统计与 SHA-256。标注 PUT 必须携带 `expected_revision`，冲突返回 HTTP 409，不静默覆盖新版本。

Operator 工单只能从已经保存的 annotation revision 创建。创建时服务端重新核对标注 ID、revision 与源图 SHA，从源图生成像素裁剪，并将像素坐标、裁剪 SHA、责任人和状态写入 revision 1。认领、纳入 CAPA、驳回或关闭必须携带 `expected_revision`，每次更新追加新的 `rev_*.json`；过期写入和非法状态迁移返回 HTTP 409。该本地队列不等于冻结 CAPA 方案已获批准，也不授予生产放行权。

默认本地数据根为：

```text
output/product/operator_workspace/usr_local_demo/wsp_local_demo/
```

这些接口不调用 OpenToken，也不把原始图片交给外部模型。它们仍是单机开发工作区；公网或多人生产部署前必须补充真实 IAM、TLS、速率/容量配额、恶意文件扫描和备份恢复。

## 3. 授权服务器本地数据源（可选）

真实/公开工业数据只有在操作者主动填写权利依据并确认只读、禁止原始数据再分发后，才能注册为 `local_authorized_directory`。目录必须位于服务端 allowlist 根下；`root_path` 只作输入，响应、任务证据和公开包只保留路径摘要。

启动 API 前需在忽略提交的 `.env.local` 中显式配置服务端允许读取的窄目录；Windows 多目录使用分号分隔。不得配置盘符根目录、用户主目录或无关共享盘：

```dotenv
VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS=E:\\authorized-data\\visiondata
```

未配置时，服务端返回 `source_not_connected` 并拒绝登记；不会为了让 Demo 跑通而静默放宽目录边界。

```powershell
$Headers = @{"X-Actor-User-Id" = "usr_local_demo"}
$SourceBody = @{
    workspace_id = "wsp_local_demo"
    display_name = "本地工业数据源"
    root_path = $ServerDatasetPath
    source_archive_sha256 = $SourceArchiveSha256
    adapter_kind = "omni_ad_30_release"
    purpose = "复赛本地只读数据治理与发布门禁验证"
    rights_basis = $RightsBasisEnteredByOperator
    residency = "server_local_in_place"
    operator_attests_authorized_use = $true
    read_only = $true
    raw_redistribution_allowed = $false
} | ConvertTo-Json

$Source = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/data-sources/local-authorizations" `
    -Headers $Headers `
    -ContentType "application/json" `
    -Body $SourceBody

$Source.source_id
```

`rights_basis` 不提供默认答案，必须由操作者根据实际授权填写。系统回执只证明“operator-attested + allowlist/profile checks”，不是独立法律权属意见、客户验收、生产批准或数据再分发许可。可用以下接口查询当前工作区可见的数据源：

```http
GET /v1/data-sources?workspace_id=wsp_local_demo
GET /v1/data-sources/{source_id}
GET /v1/data-sources/{source_id}/authorization-events
```

授权生命周期是只追加 hash chain。需要停止未来读取或使既有 CAPA 批准失效时，操作者必须携带当前最新事件 SHA 做乐观并发撤销：

```powershell
$RevokeBody = @{
    reason = "停止后续派生处理；保留既有审计回执。"
    expected_latest_event_sha256 = $Source.latest_authorization_event_sha256
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/data-sources/$($Source.source_id)/revocations" `
    -Headers $Headers `
    -ContentType "application/json" `
    -Body $RevokeBody
```

撤销会阻断未来来源读取、旧 CAPA 批准和执行重放，但不声称删除操作者原位管理的源字节，也不替代法律权属判断。

## 4. 提交并查询任务

```powershell
$Headers = @{
    "X-Actor-User-Id" = "usr_local_demo"
    "Idempotency-Key" = "batch-demo-001"
}

$Body = @{
    project_id = "prj_industrial_vision"
    goal = "审核这批数据，生成整改任务，并在同一规则下复验"
    seed = 20260809
    source_kind = "local_authorized_directory"
    source_id = $Source.source_id
    plan_approval_required = $true
    allowed_tools = @(
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
        "governance_audit"
    )
} | ConvertTo-Json

$Task = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks" `
    -Headers $Headers `
    -ContentType "application/json" `
    -Body $Body

$TaskId = $Task.task_id
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/plan" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}

$Preflight = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/preflight" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}

$Preflight.overall_status
$Preflight.prerequisite_ready

$Approval = @{
    action = "approve_plan"
    note = "已核对只读范围、工具权限、补证预算与生产人工审批边界。"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/interventions" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"} `
    -ContentType "application/json" `
    -Body $Approval

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}
```

执行生命周期与门禁决定是两套字段：

```text
execution_status: CREATED → PLANNED → RUNNING → VERIFYING → COMPLETED / FAILED
                              └→ CANCELLED（仅工具调用前）
final_decision:   PASS / RECAPTURE / QUARANTINE / DEFER
```

`COMPLETED + DEFER` 表示系统正确完成并因证据不足而暂缓，不是运行失败。

`plan_approval_required=true` 时，批准前数据库 claim 条件会阻止执行；可用
`cancel_plan` 在工具调用前取消。完成后还可追加 `acknowledge_result` 或
`request_changes`，每条干预记录绑定变更前任务快照 SHA-256 和计划 SHA-256。
`GET /preflight` 会在批准前核验任务状态、只读授权、当前 source profile、工具白名单、
Runtime 后端与生产权限边界；前置条件被阻断时，`approve_plan` 返回 409 且不写入批准记录。
执行器仍会再次核验 source profile，避免检查与实际启动之间发生漂移。
查询完整只追加时间线：

```http
GET /v1/tasks/{task_id}/interventions
```

如不提供 `source_kind/source_id`，默认运行 `synthetic_demo`。本地真实源任务会先重新计算脱敏 source profile 并与授权回执比对；数量、哈希、驻留或状态漂移均失败关闭。

## 5. Trace 与 Evidence

任务完成后：

```powershell
Invoke-WebRequest `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/trace" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"} `
    -OutFile "$TaskId-trace.json"

Invoke-WebRequest `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/evidence" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"} `
    -OutFile "$TaskId-evidence.zip"

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/industrial-delivery" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/release-readiness" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}
```

服务会将 artifact 路径限制在该任务不可变目录内，并在下载前重新核验记录的 SHA-256。未完成、跨工作区、路径越界或哈希不一致都会 fail closed。工业任务的 Evidence ZIP 还包含计划预览、构包时干预时间线和工业交付回执。

`release-readiness` 是独立的实时门禁，不改写冻结 Evidence ZIP。它同时验证证据包完整性、
当前授权数据画像是否仍与运行时快照一致、Gate 是否为 PASS、是否仍有工单，以及生产人工审批是否
仍为 pending。若数据在运行后发生变化，状态固定为 `BLOCKED_SOURCE_STALE`，旧裁决不得复用于
新数据；即使状态为 `READY_FOR_HUMAN_REVIEW`，`production_release_allowed` 仍恒为 `false`。

### 5.1 创建不覆盖父裁决的复验 Run

完成整改后，不更新旧任务或替换旧 Evidence ZIP，而是从已完成任务创建 child Run：

```powershell
$ReverificationBody = @{
    note = "已按责任队列完成整改，申请在相同规则、工具和固定种子下复验。"
    # 若整改后的数据已登记为新的只读授权版本，在此填写新的 source_id。
    # source_id = "src_..."
} | ConvertTo-Json

$Child = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/reverifications" `
    -Headers @{
        "X-Actor-User-Id" = "usr_local_demo"
        "Idempotency-Key" = "reverify-$TaskId-v1"
    } `
    -ContentType "application/json" `
    -Body $ReverificationBody

$ChildId = $Child.task_id
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$ChildId/lineage" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}
```

child Run 强制 `plan_approval_required=true`，并继承父任务的项目、场景规则、工具白名单和固定
种子。数据库中的只追加 lineage edge 同时绑定父 `request_sha256`、父 `evidence_sha256` 与
`reverification-contract` SHA；任何边都不能 UPDATE/DELETE。新 Run 仍需重新通过 Preflight，
因此旧授权与整改后目录画像不匹配时会被阻断，必须先登记新的只读数据版本。

`GET /lineage` 返回哈希封印的完整运行族。它证明本地父子绑定和合同继承，不等于整改正确、客户
验收或生产放行。

### 5.2 执行受控 CAPA，而不是只生成工单

先读取工业交付回执中的三套冻结方案，选择时同时提交 `plan_id` 与 `plan_sha256`：

```powershell
$Delivery = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/industrial-delivery" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}

$Plan = $Delivery.remediation_plans | Where-Object {
    $_.strategy -eq "full_evidence_closure"
} | Select-Object -First 1

$Selection = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/capa-cases" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"} `
    -ContentType "application/json" `
    -Body (@{
        plan_id = $Plan.plan_id
        plan_sha256 = $Plan.plan_sha256
        note = "选择完整闭环方案；失败结果必须保留并转入责任队列。"
    } | ConvertTo-Json)

$CaseId = $Selection.case_id
$Approval = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/capa-cases/$CaseId/approval" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"} `
    -ContentType "application/json" `
    -Body (@{
        note = "只允许在私有派生版本执行；父来源保持只读。"
        approved_work_order_ids = $Plan.selected_work_order_ids
        operator_attests_derived_processing = $true
        source_mutation_permitted = $false
        raw_redistribution_allowed = $false
        max_copied_images = 180
    } | ConvertTo-Json -Depth 5)

$Executed = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/capa-cases/$CaseId/execute" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}
```

查询与审计：

```http
GET /v1/tasks/{task_id}/capa-cases
GET /v1/tasks/{task_id}/capa-cases/{case_id}
GET /v1/tasks/{task_id}/capa-cases/{case_id}/outcome-assessment
GET /v1/tasks/{task_id}/capa-cases/{case_id}/governed-outcome-envelope
```

批准同时绑定父 request/Evidence、工业交付、规则合同、来源画像、最新授权事件、方案和责任队列 SHA。任一回执篡改、来源漂移、授权撤销、复制预算不足或跨回执错配都会失败关闭。执行只写产品私有派生版本，创建独立 child Run；父来源与父 Evidence 保持不可变。派生版本 v2 使用同盘 staging、完整回读校验和不覆盖目标的目录重命名；这是目录发布原子性，不是跨数据库、来源授权与 Child Run 的全局事务。

`governed-outcome-envelope` 只对“一个 Incident 的具名决定精确绑定一个已完成 CAPA/Child Run”的流程可用。它按固定顺序绑定 12 类源工件并返回 `ETag` 与 `X-Content-SHA256`；服务每次读取都会重新对照源工件，即使有人修改 Envelope 后重算本地根，也不能替换真实闭环。当前 `signature.status=NOT_CONFIGURED`，因此该接口不能描述为数字签名、可信时间戳或外部不可篡改存证。

真实 Omni `_05` 的最高覆盖方案已执行，但结果为 6 条责任项关闭、43 条仍开并 `TRANSFERRED_TO_INVESTIGATION`；`_06` 的最小恢复成本保持 `NOT_ESTIMABLE`。因此 API 的 `COMPLETED` 或 finding 数下降都不能被客户端解释成恢复成功或生产放行。

### 5.3 用 SHA 绑定回执完成 Goal → Goal3 交接

Goal Task 完成不等于可以直接创建工业案件。先读取只读交接回执：

```powershell
$HandoffResponse = Invoke-WebRequest `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/goal3-handoff" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}

$Handoff = $HandoffResponse.Content | ConvertFrom-Json
if ($HandoffResponse.Headers["X-Goal3-Handoff-SHA256"] -ne $Handoff.receipt_sha256) {
    throw "Goal3 handoff response header mismatch"
}
if ($Handoff.handoff_status -ne "READY_FOR_INCIDENT_INTAKE") {
    throw $Handoff.next_action
}
```

`Goal3HandoffReceipt v1` 重新核验 Task Evidence ZIP，并绑定 Task 请求摘要、作用域和最新 Incident head。它不会生成缺失的 OPC UA、批次、视觉方案或授权证据，也不会隐式创建案件。产品 Web 还会在浏览器内重新计算 RFC 8785 JCS SHA-256。

提交新的 root Incident 时，产品 Web 会把刚核验的回执摘要作为前置条件传回服务端：

```powershell
$Incident = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/industrial-incidents" `
    -Headers @{
        "X-Actor-User-Id" = "usr_local_demo"
        "Idempotency-Key" = "incident-$TaskId-v1"
        "X-Goal3-Handoff-SHA256" = $Handoff.receipt_sha256
    } `
    -ContentType "application/json" `
    -Body (Get-Content -Raw -Encoding UTF8 ".\incident-request-v3.json")
```

如果 Evidence 漂移、Task/Project 作用域变化、已有案件链形成，或 GET 与 POST 之间回执已更新，服务端返回 `409`，且不会创建第二个案件。兼容客户端未提供该请求头时，后端仍执行原有 Task/Evidence/Incident 合同校验；新 Web 和新脚本应始终携带该摘要。

### 5.4 换型后异常案件 Agent Loop

`IndustrialIncidentRequest.v2` 将一次换型后异常的脱敏触发信息与四类一等证据绑定到已完成 Gate：

- 质检数据：带 OK/NG 统计、ResultId、批次、工单和样本索引摘要的离线运行回执；
- 批次信息：MES、条码或工单导出的 `BatchTraceRecord`；
- 工艺参数：只读 OPC UA 形状快照和冻结过程窗口；
- 生产记录：批准状态、生效时间和旧/新版本明确的 `ProductionChangeRecord`。

批次与生产变更记录同时保留原始来源 SHA-256 和规范化记录绑定 SHA-256。v2 缺少批次记录或生产
变更记录会在 API 输入阶段拒绝；显式旧 v1 仍可读取，但进入 Judge 前固定失败关闭，不能借兼容路径
绕过四源合同。

```http
POST /v1/tasks/{task_id}/industrial-incidents
GET  /v1/tasks/{task_id}/industrial-incidents
GET  /v1/tasks/{task_id}/industrial-incidents/{case_id}
GET  /v1/tasks/{task_id}/industrial-incidents/{case_id}/audit-envelope
GET  /v1/tasks/{task_id}/industrial-incidents/{case_id}/phase-events
GET  /v1/tasks/{task_id}/industrial-incidents/{case_id}/decisions
POST /v1/tasks/{task_id}/industrial-incidents/{case_id}/decisions
POST /v1/tasks/{task_id}/industrial-incidents/{case_id}/resume
```

不启动 SaaS 或页面时，可以在 Windows 工业 PC 的 Conda 环境中直接运行同一基础逻辑：

```powershell
conda env create -f environment.core.yml
conda run -n visiondata-gate-core visiondata-gate incident-evaluate `
  --request incident-request.json `
  --gate-context gate-context.json `
  --output incident-case.json
```

该命令只读取显式 JSON 路径并写出案件回执，不连接真实 OPC UA、VisionMaster、MES，不执行设备写入。
对产品服务生成的完整案件目录，可离线重算 JCS 域摘要、事件链、治理材料与 Audit Root：

```powershell
conda run -n visiondata-gate-core visiondata-gate incident-audit-verify `
  --case-dir E:\absolute\path\to\incident_0123456789abcdefabcd
```

成功时返回 `verification_status=PASS`，签名状态仍明确为 `NOT_CONFIGURED`；失败返回码为 `2`。
该能力是确定性血缘复验，不是数字签名、可信时间戳、因果证明或行业认证。协议与兼容矩阵见
[`GOVERNED_AUDIT_ENVELOPE.md`](GOVERNED_AUDIT_ENVELOPE.md)。
当前候选版本未放置未经编译验证的 Spring Boot 壳；企业侧以后可由 Spring Boot 承担 IAM、租户、
审批和 MES/WMS/ERP 接口，再调用现有 HTTP/JSON Agent 合同。

v3 案件执行的是有界 `PLAN → ACT → OBSERVE → EVALUATE → INTERRUPT` 循环。每个真正执行的
专业 Worker 都产生绑定输入证据、工具合同、输出问题和版本的回执；未执行或因预算停止的 Worker
不能向 Judge 提交问题，失败 Worker 也不得发布供 Judge 使用的问题。制造上下文 Worker 会检查
批次身份、唯一工单、质检结果批次、生产时间窗和变更授权；有效生产记录只能形成支持或反驳假设的
证据边，不能把时间相关性升级成根因。`phase-events` 将每个阶段和 Worker invocation 的输入/输出 SHA、状态、
错误码、可重试性及前序事件 SHA 逐条返回，任一文件被改写都会使案件读取失败关闭。

人工决定必须绑定当前 `case_sha256`。同一案件只允许一条活动决定；相同请求幂等返回，不同决定
冲突。选择整改方案会创建确定性、精确绑定的 CAPA，但不会自动批准或执行。续跑时请求体除新证据
外必须同时携带以下三个字段，缺一即拒绝：

```json
{
  "supersedes_case_id": "incident_...",
  "expected_parent_case_sha256": "64-hex",
  "authorizing_decision_id": "incident_decision_..."
}
```

续跑不会修改父案件；一条人工决定只能形成一个不可变 child head。若决定选择了整改方案，新案件只
加载该决定绑定的精确 CAPA selection、approval、derived version、execution、recovery 和 child
Evidence SHA。child Run 即使观察到数据恢复，只要工艺窗口或视觉方案冲突仍未关闭，案件仍返回
`INVESTIGATION_REQUIRED`，不会升级成恢复成功或生产放行。

## 6. 导出整改任务与拉回修订

任务完成后可生成 CVAT 或 FiftyOne 整改合同：

```powershell
$Export = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/annotation-exports/cvat" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}

$Export.bundle.export_id
$Export.bundle.connector_state
$Export.bundle.external_connected
```

初始输出固定为 `contract_ready_not_connected / false`。系统不会因为导出了 JSON 就冒充已连接 CVAT。回传包遵循 `visiondata-gate.annotation-import.v1`，每条 revision 必须携带 export 中的 work order、sample key、源图 SHA-256、前序标注 SHA-256/版本和 base64 PNG mask：

```http
POST /v1/tasks/{task_id}/annotation-imports
Content-Type: application/json

{
  "schema_version": "visiondata-gate.annotation-import.v1",
  "export_id": "annexp-...",
  "provider": "cvat",
  "revisions": [
    {
      "work_order_id": "wo-...",
      "internal_sample_id": "...",
      "external_sample_key": "vdg:...",
      "external_task_id": null,
      "source_image_sha256": "...",
      "prior_annotation_sha256": null,
      "annotation_version": "review-v2",
      "annotation_content_base64": "..."
    }
  ]
}
```

服务不接受客户端文件路径。合格 bytes 写入任务外的独立 roundtrip 目录，原批次保持不变，并在相同 `BatchContract` 下重新 Gate。查询回执：

```http
GET /v1/tasks/{task_id}/annotation-roundtrips
```

`local_contract_verified` 只表示本地 sample/version/hash/recheck 合同成立；回传 JSON、回执侧车、复验 manifest 与 GateResult 会交叉校验。外部连接仍由 `external_connected` 单独说明，CVAT 需要只读可达与身份探测同时成功，FiftyOne 库可导入本身不算连接。

## 7. 企业验收 Scorecard

```powershell
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/acceptance-scorecard" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}
```

Scorecard 包含模型无证据主张率、引用有效率、动态触发 precision/recall、工单往返保真度、整改闭环率、批次时延、模型计费状态、关键错误放行率与所有外部连接状态。没有真实分母或回执的指标返回 `NOT_MEASURED`，不会静默填成 0。

## 8. 登记授权历史批次影子评测

影子评测只接受已完成的 `local_authorized_directory` 任务。标签摘要必须绑定外部 Truth Manifest 与 Gate Output Manifest，不会写回任务 Evidence 或 Agent Core：

```powershell
$Shadow = @{
    identity = @{
        dataset_namespace = "authorized-history-v1"
        site_alias = "site-a"
        line_alias = "line-01"
        station_alias = "aoi-07"
        camera_alias = "camera-main"
        batch_alias = "batch-2026-08-29-a"
        captured_from = "2026-08-20T00:00:00+08:00"
        captured_to = "2026-08-21T00:00:00+08:00"
    }
    ground_truth_method = "dual_human_adjudication"
    truth_manifest_sha256 = "<64 位小写 SHA-256>"
    gate_output_manifest_sha256 = "<64 位小写 SHA-256>"
    confusion = @{
        unit_of_analysis = "inspection image"
        true_block_count = 17
        false_release_count = 1
        true_release_count = 31
        false_block_count = 3
    }
    remediation = @{
        verified_pass_count = 8
        verified_fail_count = 2
        unresolved_count = 2
    }
    note = "两位质量复核人已完成历史批次标签仲裁。"
    operator_attests_authorized_historical_use = $true
    operator_attests_labels_reviewed = $true
    read_only_shadow = $true
    raw_images_transmitted = $false
    machine_write_permitted = $false
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId/industrial-shadow-evaluations" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"} `
    -ContentType "application/json" `
    -Body $Shadow
```

重复提交完全相同的请求会返回同一 `shadow_*` 回执。误放行分母是所有“应拦截”单元，误拦截分母是所有“可放行”单元，整改通过率分母只包含完成同合同复验的整改；未决整改另列，不从分母中消失。查询：

```http
GET /v1/tasks/{task_id}/industrial-shadow-evaluations
```

该回执是操作者声明与 SHA 绑定，不是独立客户验收、在线产线部署、法律权属证明或生产放行。

## 9. 当前边界

- `synthetic_demo` 可直接使用；`local_authorized_directory` 已实现并完成一次操作者授权的本地产品实跑，仍需服务端 allowlist、源哈希、只读和禁止再分发声明；`external_residency_reference` 保持未连接。
- 2026-08-25 验证运行只读 profile 4,464 张图像/1,439 个 masks，并对固定 180 张执行 Gate；它不代表 4,464 张全量 Policy Gate、客户数据验收或独立法律权属认证。
- CVAT/FiftyOne 整改适配合同已实现并本地验证；默认 health 状态为 `contract_ready_not_connected`，不是外部服务连接成功。
- 账户 bootstrap 默认关闭；显式初始化模式也只用于受信本地建库，不是注册、登录或租户管理服务。
- 客户 BYOK 已通过回环管理接口和“设置 → 模型接入”进入 Provider Profile；远程 Key 仅在提交时进入内存，并在 Windows 使用 DPAPI 保存密文，不写入案件 JSON、普通数据库、日志或回执。该能力仍是 `LOCAL_BYOK_READY / PRODUCTION_AUTH_NOT_CONFIGURED`，不是公网多租户密钥服务。API 仍不接受客户端任意文件系统路径。
- 没有生产级认证、加密、速率限制、租约调度、客户部署或 SLA。
- Hosted AgentTeams transport 已有显式配置、只读 probe、具名提交与回执合同；默认保持 `NOT_CONFIGURED`，没有一次成功远程回执时不得宣称已连接或已托管执行。
- 本地 Omni 数据已在操作者授权声明和服务端 allowlist 下只读进入产品链；原始图像、mask、类别名、文件名和绝对路径未复制或打入证据包。公开/复赛交付只允许脱敏 profile、摘要、GateResult 和哈希回执。
