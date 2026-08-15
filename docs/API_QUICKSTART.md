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

## 2. 本地演示对象

工作台或默认 API 首次启动会原子创建一组固定的本地演示对象：

```text
user_id       usr_local_demo
workspace_id  wsp_local_demo
project_id    prj_industrial_vision
```

默认 API 不公开用户创建、用户枚举或工作区创建接口，避免把匿名本地引导误当成账户管理面。需要新增本地演示用户与工作区时，请在工作台“项目”页使用本地初始化入口；项目和审核任务可通过 API 创建。`X-Actor-User-Id` 只用于本地成员关系与逻辑作用域演示，不是登录认证、API Key 或生产 IAM。

## 3. 提交并查询任务

```powershell
$Headers = @{
    "X-Actor-User-Id" = "usr_local_demo"
    "Idempotency-Key" = "batch-demo-001"
}

$Body = @{
    project_id = "prj_industrial_vision"
    goal = "审核这批数据，生成整改任务，并在同一规则下复验"
    seed = 20260809
    allowed_tools = @(
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix"
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
    -Uri "http://127.0.0.1:8787/v1/tasks/$TaskId" `
    -Headers @{"X-Actor-User-Id" = "usr_local_demo"}
```

执行生命周期与门禁决定是两套字段：

```text
execution_status: CREATED → PLANNED → RUNNING → VERIFYING → COMPLETED / FAILED
final_decision:   PASS / RECAPTURE / QUARANTINE / DEFER
```

`COMPLETED + DEFER` 表示系统正确完成并因证据不足而暂缓，不是运行失败。

## 4. Trace 与 Evidence

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
```

服务会将 artifact 路径限制在该任务不可变目录内，并在下载前重新核验记录的 SHA-256。未完成、跨工作区、路径越界或哈希不一致都会 fail closed。

## 5. 当前边界

- 仅 `synthetic_demo` 已连接；`local_authorized_directory` 与 `external_residency_reference` 保持未连接。
- 账户 bootstrap 默认关闭；显式初始化模式也只用于受信本地建库，不是注册、登录或租户管理服务。
- 不接受 API Key、任意模型 endpoint 或客户端文件系统路径。
- 没有生产级认证、加密、速率限制、租约调度、客户部署或 SLA。
- AgentTeams 仍为 `mapped_not_connected`。
- 海康 / Omni 数据在授权、驻留和脱敏范围确认前不会被读取、复制或打入公开参赛包。
