# API 快速接入：真实身份与第一个可核验结果

本页使用当前本地 FastAPI / ProductService。React 是首选交互界面，Streamlit 仅保留兼容用途。示例生成合成数据，不需要客户目录、GPU、模型 Key 或权重；不是生产 IAM、工厂效果或客户验收证明。

先选 [采用路径](ADOPTION_GUIDE.md)。需要 Python 3.12/3.13、uv；浏览器路径另需 Node.js 22.12+。从选定提交的仓库根目录安装锁定依赖：

```text
uv sync --locked --extra api --extra qa
```

## 1. 选择启动路径

### 推荐：浏览器启动器自动处理 startup capability

```text
npm --prefix web ci
uv run --no-sync python tools/run_cross_platform_workbench.py --check
uv run --no-sync python tools/run_cross_platform_workbench.py
```

使用启动器打开的会话，完成首个具名管理员设置。控制台不带 capability 的裸 URL 不能代替初始化会话。默认 API 是 http://127.0.0.1:8787；自选端口时客户端用同一端口。保持启动器运行，停止时只关闭它拥有的服务。[跨平台启动与排错](CROSS_PLATFORM_QUICKSTART.md)

### 可选：Windows 纯 API 服务

run_api.ps1 没有 session capability 时会拒绝启动，不应关闭这个检查。以下要求 PowerShell 7，以隐藏输入读入本轮高熵随机 capability。请在受信密码管理器生成至少 32 字符的随机值，不把真实值写入命令历史、源码、共享日志或截图。

在终端 A 使用全新数据目录，保持服务运行：

```powershell
$StartupCapability = Read-Host '本轮随机启动 capability（不回显）' -MaskInput
if ($StartupCapability.Length -lt 32) { throw 'capability 长度不足' }
if (Test-Path -LiteralPath './output/api-quickstart-01') { throw '请选择未使用的数据目录' }
./run_api.ps1 -Port 8787 -ProductRoot './output/api-quickstart-01' -SessionToken $StartupCapability
```

终端 B 运行第 3 节客户端。首次设置时隐藏输入同一个 capability；已完成设置则直接登录。startup capability、用户密码、模型 Key 三者不同。此 Windows 脚本会读取已有 .env.local，仅在审查过该本地配置后使用；推荐便携启动器默认不读取它。

公开健康接口是 /v1/health，OpenAPI 为 /openapi.json 与 /docs。它们可访问，不代表私有业务请求已授权。

## 2. 当前身份协议

| 动作 | 实际接口 | 权限边界 |
|---|---|---|
| 状态 | GET /v1/identity/status | 返回 setup_required、identity_required；不回传密钥 |
| 首个管理员 | POST /v1/identity/setup | 数值回环连接与 X-VisionData-Session-Token 启动 capability；服务端绑定 actor，客户端不能自选角色 |
| 普通注册 | POST /v1/identity/register | 返回 PENDING 账户，不返回 Bearer，不自动获得工作区权限 |
| 登录 | POST /v1/identity/login | 有效 ACTIVE 账户获得 user、access_token、token_type=Bearer、到期时间 |
| 私有业务请求 | Authorization: Bearer（仅内存中的实际令牌） | 身份与工作区/项目权限共同决定可见范围 |
| 自有工作区 | POST /v1/workspaces | owner_user_id 取当前 GET /v1/identity/me，不用固定演示 ID |
| 退出 | POST /v1/identity/logout | 撤销当前客户端的会话 |

setup/register 字段为 login_name、display_name、password，可选 email；新密码至少 12 字符，不 trim 密码。login 只提交 login_name、password。普通注册须先由管理员通过 /v1/identity/admin/users/{user_id}/approve 批准；工作区授权仍是独立动作。

X-Actor-User-Id 不是认证，通常不必发送；若发送必须匹配 Bearer 用户。初始化前这个头不能代替 startup capability，初始化后 capability 不能代替用户 Bearer。ACTIVE 或 ADMIN 不代表拥有其他人的业务数据。

VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS 只属于显式隔离的测试夹具。正常部署禁止启用，不应把只有 actor header 的旧测试请求复制到用户环境。

## 3. 可直接运行并受测试覆盖的 HTTP 客户端

将以下代码保存到自己选定的本地 api_example.py，服务运行时执行：

```text
uv run --no-sync python api_example.py
```

httpx 已由锁定 QA 依赖提供。例子创建新工作区、新项目与 synthetic_demo 任务；展示计划后需要输入 APPROVE 才执行。不依赖可选私域数据源或维护者的原图，不加载模型，不自动重试 POST。输出只含 ID、状态和摘要，不含真实 token 或密码。

```python
# doc-contract: authenticated-synthetic-run
import getpass
import hashlib
import json
import time
import uuid

import httpx


def run_synthetic_example(client, login_name, password, display_name, review_plan,
                          *, startup_capability=None):
    def json_request(method, route, **kwargs):
        response = client.request(method, route, **kwargs)
        response.raise_for_status()
        return response.json()

    state = json_request("GET", "/v1/identity/status")
    account = {"login_name": login_name, "password": password}
    if state["setup_required"]:
        if not startup_capability:
            raise RuntimeError("setup_required: use the owned launcher or supply its startup capability")
        auth = json_request("POST", "/v1/identity/setup",
                            headers={"X-VisionData-Session-Token": startup_capability},
                            json={**account, "display_name": display_name})
    else:
        auth = json_request("POST", "/v1/identity/login", json=account)
    headers = {"Authorization": "Bearer " + auth["access_token"]}
    try:
        user = json_request("GET", "/v1/identity/me", headers=headers)
        suffix = uuid.uuid4().hex[:12]
        workspace = json_request("POST", "/v1/workspaces", headers=headers,
                                 json={"name": "API adoption " + suffix,
                                       "owner_user_id": user["user_id"]})
        project = json_request("POST", "/v1/projects", headers=headers,
                               json={"workspace_id": workspace["workspace_id"],
                                     "name": "Synthetic first result " + suffix,
                                     "source_kind": "synthetic_demo"})
        request_key = "adoption_" + uuid.uuid4().hex
        print(json.dumps({"pending_operation": "create_task", "request_key": request_key,
                          "workspace_id": workspace["workspace_id"],
                          "project_id": project["project_id"]}, ensure_ascii=False))
        task = json_request("POST", "/v1/tasks",
                            headers={**headers, "Idempotency-Key": request_key},
                            json={"project_id": project["project_id"],
                                  "goal": "Review generated synthetic data and preserve human authority",
                                  "seed": 20260809, "source_kind": "synthetic_demo",
                                  "plan_approval_required": True})
        route = "/v1/tasks/" + task["task_id"]
        plan = json_request("GET", route + "/plan", headers=headers)
        preflight = json_request("GET", route + "/preflight", headers=headers)
        summary = {"workspace_id": workspace["workspace_id"],
                   "project_id": project["project_id"], "task_id": task["task_id"],
                   "request_key": request_key, "source_kind": task["source_kind"],
                   "production_release_allowed": False}
        print(json.dumps({"created": summary}, ensure_ascii=False))
        if not preflight["prerequisite_ready"]:
            raise RuntimeError("HOLD: inspect this task preflight; do not bypass it")
        if not review_plan(plan, preflight):
            return {**summary, "execution_status": "PLANNED", "human_approval": "NOT_GIVEN"}
        json_request("POST", route + "/interventions", headers=headers,
                     json={"action": "approve_plan",
                           "note": user["display_name"] + ": reviewed this synthetic plan; no production authority"})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            task = json_request("GET", route, headers=headers)
            if task["execution_status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.2)
        if task["execution_status"] != "COMPLETED":
            raise RuntimeError("Task not completed; preserve its ID and use GET to reconcile")
        hashes = {}
        for name, field in (("trace", "trace_sha256"), ("evidence", "evidence_sha256")):
            response = client.get(route + "/" + name, headers=headers)
            response.raise_for_status()
            observed = hashlib.sha256(response.content).hexdigest()
            if observed != task[field]:
                raise RuntimeError("HOLD: downloaded artifact SHA mismatch")
            hashes[field] = observed
        readiness = json_request("GET", route + "/release-readiness", headers=headers)
        if readiness["production_release_allowed"] is not False:
            raise RuntimeError("HOLD: unexpected production authority")
        return {**summary, "execution_status": task["execution_status"],
                "final_decision": task["final_decision"], **hashes,
                "release_readiness": readiness["overall_status"]}
    finally:
        # Revoke this session only; do not print or persist its Bearer.
        client.post("/v1/identity/logout", headers=headers).raise_for_status()


if __name__ == "__main__":
    def review(plan, preflight):
        print(json.dumps({"plan": plan, "preflight": preflight}, ensure_ascii=False, indent=2))
        return input("复核合成计划后输入 APPROVE；其他输入保留待批准: ") == "APPROVE"

    with httpx.Client(base_url="http://127.0.0.1:8787", timeout=30,
                      follow_redirects=False, trust_env=False) as client:
        status = client.get("/v1/identity/status")
        status.raise_for_status()
        capability = getpass.getpass("同一个启动 capability（仅首次设置）: ") if status.json()["setup_required"] else None
        name = input("登录名: ")
        display = input("具名显示名（首次设置）: ") if capability else name
        password = getpass.getpass("用户密码（不回显）: ")
        result = run_synthetic_example(client, name, password, display, review,
                                       startup_capability=capability)
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

工作区、项目与任务身份全部取服务端返回。客户端不跟随 HTTP 重定向、不使用代理环境，不把凭据写磁盘；退出撤销当前会话。原始 Trace/Evidence 留在私有服务存储，公开前需要另行脱敏。

**示例 PASS：**未经批准保持 PLANNED；批准后 COMPLETED；下载的 Trace/Evidence 字节 SHA 与任务记录相同；生产权限始终 false。最终 Gate 可以为 PASS、RECAPTURE、QUARANTINE 或 DEFER，不为示例强求数据放行。

工作区和项目创建没有任务式 Idempotency-Key 合同。若其 POST 结果未知，保留已知 ID，GET 查看当前账户的工作区/项目并人工核查；仅同名不能证明某次写入成功，不自动重建。任务 POST 使用精确 idempotency key，未知结果只 GET 对账，不自动从头重跑脚本。

## 4. 后续接口与排错

请求体以本版本 /openapi.json 和版本化 Schema 为准；仍需要用户 Bearer 与作用域权限。

| 用途 | 真实入口 |
|---|---|
| 计划、前置条件、人工决定 | /v1/tasks/{task_id}/plan、/preflight、/interventions |
| Trace、证据、实时放行准备 | /v1/tasks/{task_id}/trace、/evidence、/release-readiness |
| 图片、人工框与工单 | /v1/operator-workspaces/{workspace_id}/assets 及其 annotations/work-orders；绑定实际 revision |
| 自备授权来源 | /v1/data-sources/local-authorizations；另需 allowlist、权利依据、源 SHA，初次示例无需此路径 |
| 可选视觉模型 | [模型 API](VISION_MODEL_API_CONTRACT.md)、[Normality TTT](NORMALITY_TTT.md) |
| Python 组件复用 | [公共 API](PUBLIC_API.md)、[SDK 示例](../examples/reuse/README.md) |

- 启动缺 session：提供合法 capability 或使用推荐启动器，不开启测试 bypass。
- setup_required=true：按真实 setup 接口和回环 capability 初始化；不猜端点或自选 actor/角色。
- 401：缺少、无效、过期或撤销的 Bearer；重新登录，不换 actor header 冒充身份。
- 403/404：检查账户审批和实际工作区/项目权限，管理员不是全局业务 owner。
- 409：先读版本、摘要、前置条件和状态；不无限重发。
- 网络中断：保留 ID、request key 和失败阶段，仅 GET 对账；不删库或换 key 自动重做。
- 无外部模型/权重时核心路径仍可运行；模型页保持 HOLD，不自动下载或用参考模型冒充工业检测。
- 工单存在不等于 CAPA 已执行、责任关闭；模型更新不等于精度提高；Provider Profile 不等于连接成功。

这是本地应用身份控制，不是公网生产 IAM。TLS、生产配额、恶意文件扫描、独立备份恢复和客户验收需要另行设计验证。[能力边界](CAPABILITY_STATUS.md)、[身份测试](../tests/test_identity_api.py)、[第三方复现记录](THIRD_PARTY_REPRODUCTION.md)。
