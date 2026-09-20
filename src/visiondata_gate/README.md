# 核心代码导航

从所需能力进入，不必复制整个工作台，也不必先理解全部历史实验模块。

| 层次 | 主要入口 | 复用边界 |
| --- | --- | --- |
| 包级公开 API | [__init__.py](__init__.py)、[contracts.py](contracts.py) | 0.1 系列包根只承诺 `GateDecision`；其他入口按模块/协议固定版本 |
| 数据合同与状态 | [contracts.py](contracts.py)、[operator_snapshot.py](operator_snapshot.py)、[task_store.py](task_store.py) | 保留用途、样本身份、标注修订、任务和版本关系 |
| 确定性检查 | [quality.py](quality.py)、[duplicates.py](duplicates.py)、[annotations.py](annotations.py)、[rulepack.py](rulepack.py) | 数值和证据定位可复算；规则通过不等于生产放行 |
| Agent 编排 | [agent_runtime.py](agent_runtime.py)、[incident_agent_kernel.py](incident_agent_kernel.py)、[worker_selection.py](worker_selection.py) | 复用规划和 Worker 选择时保留白名单、预算、状态与失败合同 |
| 人工决定与复验 | [incident_interaction.py](incident_interaction.py)、[capa.py](capa.py)、[governed_outcome.py](governed_outcome.py) | 建议、批准、派生执行和 Child 复验分权处理 |
| 可执行测量 Skill | [industrial_skills.py](industrial_skills.py) | 受信实例显式注册、精确版本调用、回执复核；不是任意代码沙箱 |
| 外部观察适配 | [adapter_sdk.py](adapter_sdk.py) | 对 Adapter manifest/observation 做离线 conformance；不代表外部服务已连接 |
| 数据池与学习 | [data_pool.py](data_pool.py)、[learning_service.py](learning_service.py)、[local_model_registry.py](local_model_registry.py) | 保留 Gate、数据划分、父模型、反馈和评测身份 |
| Normality 单次适应 | [normality_ttt.py](normality_ttt.py)、[normality_adaptation_service.py](normality_adaptation_service.py)、[normality_adaptation_api.py](normality_adaptation_api.py) | 当前会话更新克隆 student；父包、主干和阈值冻结，独立 Guard 可拒绝或回滚；不是永久在线学习 |
| 模型信号转人工待办 | [normality_followup_service.py](normality_followup_service.py)、[normality_followup_api.py](normality_followup_api.py)、[operator_workspace.py](operator_workspace.py) | 反馈先导入工作簿，人保存真实框后再创建 OPEN 工单；不自动确立标签真值或训练资格 |
| HTTP 与产品服务 | [api.py](api.py)、[product_service.py](product_service.py) | 完整集成优先使用现有 API/服务边界，不绕过权限和持久化 |

## 三个起点

- [运行一个真实 SDK 示例](../../examples/reuse/README.md)
- [运行统一开放复用验收](../../docs/ADOPTION_GUIDE.md)
- [公共 API 与兼容边界](../../docs/PUBLIC_API.md)
- [选择最小复用组件](../../docs/OPEN_REUSE_CONTRACTS.md)

模块存在不代表全部导出都属于稳定 API。下划线名称为内部实现；带 `_v2`、`_v3`、`_v4` 的模块可能对应不同冻结协议，不是可以直接互换的新旧实现。

[版本与兼容](../../docs/VERSIONING.md) · [许可证与分发](../../docs/LICENSING.md) · [自研和第三方边界](../../docs/DEVELOPMENT_PROVENANCE.md)
