# 自研贡献、第三方依赖与 AI 辅助开发

VisionData Gate 的领域工作是把工业视觉的数据用途、质量检查、证据补全、人工决定、派生整改、独立复验及模型反馈组织为可核验流程。以下区分代码归属、外部依赖与验证范围，不以模块数量或框架包装作为创新结论。

## 项目内实现

| 层次 | 主要工作 | 公开入口 |
|---|---|---|
| 数据合同与质量检查 | 图像/标注/划分约束、Finding、测点与判断分离 | `contracts.py`、`quality.py`、`duplicates.py`、`annotations.py` |
| 证据驱动编排 | 竞争假设、证据缺口、Worker 选择/拒绝、依赖执行与停止条件 | `worker_selection.py`、`incident_agent_kernel.py`、`industrial_incident.py` |
| 人工决定与整改复验 | 具名确认、Parent/Child 身份、派生版本及持续/回归问题对比 | `incident_interaction.py`、`capa.py`、`governed_outcome.py` |
| 工件完整性 | 领域分隔摘要、来源引用与读取校验 | `audit_envelope.py`、`incident_decision_packet.py` |
| 工作台与学习交接 | 图像工作簿、权限与账户、数据冻结、模型/反馈身份 | `web/src/`、`identity_service.py`、`learning_service.py`、`local_model_registry.py` |
| 评测协议 | 固定输入、对照策略、失败情形与结果封存 | `architecture_benchmark.py`、`dynamic_benchmark*.py`、`industrial_incident_benchmark.py` |

路径均位于 `src/visiondata_gate/`，另注明的 Web 路径除外。这些是项目内组织和实现的内容，不表示每种底层算法由项目首次提出。

## 第三方能力

- React、Tauri、Spring WebFlux、FastAPI 承担界面、桌面外壳与服务框架。
- NumPy、Pillow、Pydantic 等提供计算、图像和校验基础；Laplacian、dHash、梯度下降、JCS 和 SHA-256 等既有方法不作为项目原创算法。
- PyTorch/Ultralytics 和预训练权重是可选视觉执行依赖。Normality 实验使用冻结预训练骨干及项目训练的特征重建头；不能将预训练骨干称为自研大模型。
- 外部 LLM/API 通过显式配置接入。一次运行是否调用模型，以该次 transport/usage/执行回执为准；静态回放和确定性 benchmark 不冒充实际 LLM 调用。

具体版本以 `uv.lock`、`web/package-lock.json`、`web/src-tauri/Cargo.lock`、`gateway/pom.xml` 及构建清单为准。现有 SBOM 不自动代表完整安装器的 Maven/JRE/原生依赖全覆盖。

## AI 辅助开发说明

项目开发过程中使用了 AI 编码助手辅助代码生成、重构、测试、排错和文档编写。需求方向、领域约束、设计取舍和最终内容由项目维护者负责审核；AI 生成的实现仍需通过测试、实际运行和来源/依赖检查。

本声明不将 AI 生成代码说成人工逐行编写，不声称所有贡献具有逐行来源证明。使用 AI 编码助手与产品运行时调用模型是不同事实：开发时使用 AI，不意味着 Demo 每次执行都调用 LLM。

## 复用与许可

项目代码按 Apache-2.0 提供，保留 LICENSE、NOTICE 和必要版权声明。第三方模型、权重与库遵循各自许可；尤其 Ultralytics 的 AGPL/Enterprise 条款不被进程隔离豁免。

发布问题请提供合成复现输入和明确提交版本，勿上传客户图像、密钥、个人账户或原始私有日志。详见 [贡献指南](../CONTRIBUTING.md)、[第三方声明](THIRD_PARTY_NOTICES.md)、[安全策略](../SECURITY.md)。
