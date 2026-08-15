# AgentTeams v1.2.2 真实接入与回执门禁

## 当前结论

项目已提供与官方 `agentteams.io/v1beta1` 对齐的 Worker / Team 资源、`Worker.spec.skills` 分发计划、静态 conformance receipt 和真实 Matrix receipt 校验器。当前机器没有可用 Docker/Podman，WSL 发行版也无法挂载，因此本地状态必须保持 `mapped_not_connected`。

这份门禁有两个独立状态：

- `static_status=PASS`：资源形状、角色数、唯一 Team Leader、Skill 元数据和本地事实边界通过。
- `runtime_validation.status=PASS`：只有真实 AgentTeams Team、Matrix 事件和 Skill assignment 的原始导出文件存在且 SHA-256 一致时才成立。

静态 PASS 不会升级为 `connected`。

## 已对齐的官方版本

- Repository: `https://github.com/agentscope-ai/AgentTeams`
- Version: `v1.2.2`
- Commit: `aa650ccacc2ba6171d1b0b5efd2a49b1472abe5d`
- API: `agentteams.io/v1beta1`
- 关键语义：Worker CR、Team CR、唯一 `team_leader`、Team Room、成员 Ready、`Worker.spec.skills`、Project/Task DAG、Matrix assignment exactly-once retry。

## 生成部署资源

```powershell
.venv\Scripts\python.exe tools\agentteams_v122_bridge.py export `
  --output output\agentteams-v122
```

生成：

- `agentteams_v122_resources.yaml`
- `agentteams_v122_skill_distribution.json`
- `agentteams_v122_conformance.json`

资源文件不含 API Key、Matrix 密码或生产授权。

## 外部前置条件

1. Docker Desktop/Engine 或 Kubernetes 1.24+。
2. 至少 2 CPU / 4 GB RAM；多个 Worker 建议 4 CPU / 8 GB RAM。
3. 经授权的 OpenAI-compatible 模型端点、模型名与 API Key。
4. AgentTeams v1.2.2 实例。

安装系统组件、写入模型密钥和调用付费模型必须由账号持有人授权；项目不会把占位值写成回执。

## 真实运行后必须导出的三份原始证据

1. `team-status.json`：Team 名、`phase=Active`、`teamRoomID`、`leaderReady=true`、`readyWorkers=totalWorkers` 和成员状态。
2. `matrix-assignment.json`：Team Room 内唯一 assignment 事件、`event_id`、worker mention，以及相同 Project/Task 重试复用同一事件的证据。
3. `skill-assignments.json`：每个 Worker 的实际 `spec.skills`；仅 Dashboard 显示文件存在不等价。

将原始文件放在 receipt 同目录的 `agentteams_runtime_raw/`，逐文件计算 SHA-256，再从 `agentteams/runtime_receipt.template.json` 复制生成：

```text
agentteams_runtime_receipt.external.json
agentteams_runtime_raw/team-status.json
agentteams_runtime_raw/matrix-assignment.json
agentteams_runtime_raw/skill-assignments.json
```

## 校验

```powershell
.venv\Scripts\python.exe tools\agentteams_v122_bridge.py validate-receipt `
  --receipt output\agent-demo\agentteams_runtime_receipt.external.json `
  --output output\agent-demo\agentteams_runtime_validation.json
```

必须同时满足：

- 官方 commit 匹配；
- Team 为 `visiondata-gate` 且 Active；
- Team Room ID 为真实 Matrix room ID；
- Leader 与全部 Worker Ready；
- assignment 在 Team Room exactly once；
- 重试复用同一 event ID；
- 所有资源 Worker 都有实际 Skill assignment；
- 三份原始证据存在且哈希一致。

任一项失败，状态保持 `mapped_not_connected`。该结果不是生产部署、安全认证、客户验收或官网提交回执。
