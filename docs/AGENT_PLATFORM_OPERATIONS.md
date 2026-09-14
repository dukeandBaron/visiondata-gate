# Agent 平台使用说明

工作台启动后，在左侧选择工作空间和项目，再进入“Agent 平台”（`/platform`）。关闭浏览器后，可在仓库根目录执行 `start_local_workbench.ps1 -Action open` 恢复本地会话。

## 能力、模型与用量

能力目录显示当前本地注册的确定性工具。模型配置数只代表当前操作者在该工作空间保存的配置，页面不会在打开时调用供应商。选择任务后，用量来自该任务的已保存证据：

- `ZERO_CALLS`：已有完整证据证明没有远端调用；
- `CALLS_RECORDED`：有实际调用记录；
- `UNKNOWN`：未运行、证据不可用或不能可靠核算；
- `PARTIAL`：部分供应商用量缺报，例如成功重试之前的尝试没有 Token 数据。

逻辑调用次数与传输尝试次数分开。成本未配置时显示未知，不按零元展示。它不是 StepFun 或其他提供商账户的完整账单，也不会将申请额度预估写成实际消耗。

## 中断恢复

只有 `INTERRUPTED` 状态提供具名恢复。填写实际复核人、处理依据并勾选确认后，系统保留原任务与已有文件，将原任务记为已确认中断，并创建新的 `PLANNED` 任务。点击替代任务链接，核对来源和计划，再重新批准执行。

`OWNED_RUNNING` 表示仍有执行者，不能接管。`LEGACY_UNKNOWN` 表示旧运行没有足够归属证据，需另行调查；不能仅按进程号缺失判断。`NOT_APPLICABLE` 表示任务当前不属于可恢复运行状态。

恢复请求绑定读取时的任务摘要。状态变化会拒绝旧请求；相同请求重复提交不会生成第二个替代任务。未收到写入结果时，先重新核验，不自动重放。

## 本地离线备份

先停止所有会写入该 ProductRoot 的 API、工作台进程及脚本，确认没有运行中任务。工具不会替用户停止进程；`--attest-offline` 表示操作者已完成停写确认。

独立驻留的服务不会因关闭浏览器而退出。如果不确定后台是否已经停止，可以在重启 Windows 后、尚未启动工作台时进行备份。

在仓库根目录执行，目标目录必须尚不存在：

```powershell
.\.venv\Scripts\python.exe -m visiondata_gate.product_backup backup `
  --source .\output\product `
  --destination .\output\backups\my-product-copy `
  --attest-offline
```

核验备份：

```powershell
.\.venv\Scripts\python.exe -m visiondata_gate.product_backup verify `
  --source .\output\backups\my-product-copy
```

恢复到新目录：

```powershell
.\.venv\Scripts\python.exe -m visiondata_gate.product_backup restore `
  --source .\output\backups\my-product-copy `
  --destination .\output\restored-product
```

备份包含上传图像、业务数据库和本机保存的私域工件，必须保存在受控存储中，不能提交到 GitHub 或公开网站。工具只复制 ProductRoot 内的文件；引用的外部原始数据源需要单独保存，绝对来源路径不会自动改写。DPAPI 保护的凭据仍受原 Windows 用户和机器保护，不能将这类备份宣传为跨机器密钥迁移。

恢复验证保证副本内容一致，不保证历史外部来源、模型或机台连接仍有效。启动恢复目录前应核对来源授权与路径。

## API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/v1/workspaces/{workspace_id}/agent-platform?project_id=...` | 能力、配置和任务清单 |
| GET | `/v1/tasks/{task_id}/model-usage` | 任务用量核算 |
| GET | `/v1/tasks/{task_id}/execution-recovery` | 执行归属和恢复条件 |
| POST | `/v1/tasks/{task_id}/execution-recovery` | 具名恢复到新审批任务 |

以上接口要求有效本地会话和工作空间成员身份，并返回正文摘要、强 ETag 与专用 SHA 响应头。新增恢复记录独立于 CAPA 血缘，不会把中断重试冒充成整改 Child Run。
