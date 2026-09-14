# 数据集复核与昇腾算力交接

本功能把工作目标落实为明确的输入合同，并为标注完成后的沙箱训练或评测预留可核验的算力交接接口。它不自动替代标注人员、不批准客户验收，也不直接运行生产设备。

## 用户工作路径

1. 在图像工作簿导入授权图片和标注，完成必要的框修订与人工复核。
2. 点击“冻结项目并交给 Agent”。弹窗读取当前全部图像的摘要和标注 revision/SHA；填写用途、类别词表、每张图的 train/val/test、标注要求，以及具名复核说明。
3. 明确要求后冻结 v2 快照。服务端独立核对实际资产、词表、要求与复核版本，不能只凭浏览器提交的摘要信任数据。
4. 在任务工作台确认计划并执行检查。不通过时处理工单或返回工作簿修订；新版本重新冻结并检查，不覆盖旧版本结果。
5. 已完成、实际 PASS、五类检查齐全且具备有效 v2 复核快照的任务，可以进入“算力交接”。核验输入后，填写固定镜像摘要、CANN版本要求、NPU数量、CPU、内存和时间预算，保存离线交接申请。
6. 下载已保存的元数据合同，由后续获授权的调度适配器消费。当前不会上传图片、创建远端作业或产生训练费用。

## 明确输入，而不是事后放宽规则

标注要求包括：

- `REQUIRED`：必须已有标注，否则拒绝冻结。
- `OPTIONAL`：允许无标注，但必须由操作者明确选择。
- `NOT_APPLICABLE`：该样本不适用标注；已有标注却声明不适用时拒绝冻结。
- `UNKNOWN`：仅能留在页面草稿，不能冻结成可运行合同。

样本列表必须精确覆盖当前项目全部资产；词表必须覆盖样本类别及已有框标签。每个具名复核声明绑定真实图像 SHA、标注 revision 和标注文档 SHA；名称是操作人员声明，同时保留服务端操作者身份，不冒充生产 IAM 或独立语义真值。

v2 合同写入 `acceptance_requirements_sha256` 和逐样本标注规则。历史请求不带 `acceptance_requirements` 时，仍生成原 v1 合同，旧快照、旧合同和旧工具参数不因此改变。用途说明不改变 `sandbox_experiment_training_pool` 的原安全边界。

冻结始终覆盖当前项目全部资产。要单独验证第二批数据，应新建独立项目；追加到旧项目后应明确称累计项目快照。不能只凭相同软件版本宣称两批采用了相同合同。

## 算力接口

可复用输入 Schema：[逐样本验收要求](../schemas/operator_acceptance_requirements.v1.json)、[算力交接申请](../schemas/compute_handoff_request.v1.json)。Schema 负责字段与类型校验，当前资产/版本、授权、完整范围与 Gate 结果仍须由服务端验证。

| 接口 | 动作 |
| --- | --- |
| `GET /v1/tasks/{task_id}/compute-preflight` | 核验任务、冻结数据、人工复核与工具结果，返回可准备或 HOLD 及理由 |
| `POST /v1/tasks/{task_id}/compute-handoffs` | 绑定预检摘要和幂等键，持久化本地离线申请 |
| `GET /v1/tasks/{task_id}/compute-handoffs` | 显式查询申请，供失败后的对账使用；不重放写入 |
| `GET /v1/tasks/{task_id}/compute-handoffs/{handoff_id}/export` | 重新核对源授权与冻结证据后导出元数据；过期或漂移时拒绝 |

申请记录绑定 workspace/project/task、source、snapshot、验收要求、manifest、contract 和 Gate 摘要。资源范围为 1–64 NPU、1–256 CPU 核、1–4096 GiB 内存、60–86400 秒；这些是申请校验范围，不代表某台设备具备相应资源。

镜像必须固定至 `@sha256:`，不接受浮动 `latest`。请求不接受任意 shell 命令、凭据或本地文件路径。同一个幂等键的相同请求返回原记录；不同请求复用键会失败。结果未知时，界面只允许 GET 对账；刷新失败会停止使用旧预检结果。

## CANN 与调度器的分工

CANN 是昇腾计算软件栈/运行环境需求，不是本项目应该直接假设存在的集群调度接口。实际集群还涉及设备插件、镜像、队列、身份、数据挂载和资源配额。

`ComputeSchedulerAdapter` 预留 `capabilities / submit / poll / cancel` 合同。当前仅提供 `OfflineComputeAdapter`；其提交、轮询和取消均明确返回 `CONNECTOR_NOT_CONFIGURED`，不会伪造外部任务 ID。

未来可以按部署条件适配 Kubernetes/Volcano、HAMi 或企业自有调度服务。参考 [HAMi 昇腾设备插件](https://github.com/Project-HAMi/ascend-device-plugin) 的公开说明，其部署方法按 HAMi/Volcano 不同，软切分实现还具有平台限制。因此这里不写死一个未经联调的通用 NPU 资源名或调度 URL，也不宣称已支持其所有设备/架构。

真正启用适配器前，还需完成：管理员确认的 endpoint/身份与最小权限、runtime镜像及CANN兼容性、数据传输授权和挂载映射、预算/配额、submit超时幂等对账、取消语义，以及带输入绑定的实际运行结果核验。不得把手工导入的任务状态当作已验证设备回执。

## 状态与验证边界

当前准备记录始终是 `PREPARED_NOT_SUBMITTED`；`remote_job_id=null`、`remote_execution_verified=false`、`dataset_bytes_exported=false`、`production_release_allowed=false`。

真实本地服务测试覆盖上传、标注、v2冻结、五类检查、PASS后准备、幂等冲突、读取/导出、来源撤销与篡改阻断。另有旧版/非PASS阻断与前端交互测试。这些不是 CANN 编译、NPU 实机运行、客户采用或工厂生产验证；真实调度和设备联调仍为 `NOT_TESTED`。
