# VisionData Gate 文档入口

VisionData Gate 是工业视觉训练数据的准入、整改复验与模型迭代工作台。工具产生可复算测量，Agent 依据证据缺口组织下一步，具名人员保留整改批准与最终判断。项目不直接控制设备，也不把数据 Gate 的 PASS 当成产线产品放行。

## 第一次阅读

1. [README](../README.md)：产品定位、真实能力、在线体验和安装入口。
2. [技术路线](PROJECT_TECHNICAL_OVERVIEW.md)：数据流、Agent、CAPA／Child、损失、参数更新与算力边界。
3. [现场复现](LIVE_REPRODUCTION.md)：改变输入、运行 v3／v4、启动本地工作台和 HTTP 学习参考流程。
4. [Benchmark Suite](../benchmarks/README.md)：每项实验的问题、协议、结果和适用范围。
5. [当前状态与证据](README_STATUS_AND_EVIDENCE.md)：源码、Demo、安装候选、测试和仍未完成事项。

## 按任务查找

| 需要做什么 | 文档 |
| --- | --- |
| 本地启动 Web／API | [跨平台快速开始](CROSS_PLATFORM_QUICKSTART.md) · [运行说明](RUNNING.md) |
| 安装 Windows 候选 | [Windows 安装指南](WINDOWS_INSTALLER.md) |
| 接入 API 或外部 Planner | [公共 API](PUBLIC_API.md) · [Planner 配置](INCIDENT_MODEL_PLANNER.md) |
| 复用 Tool／Skill／Adapter | [工业 Skill SDK](INDUSTRIAL_SKILL_SDK.md) · [开放复用合同](OPEN_REUSE_CONTRACTS.md) |
| 理解审计和哈希 | [审计信任边界](AUDIT_TRUST_BOUNDARY.md) · [Governed Outcome](GOVERNED_OUTCOME_ENVELOPE.md) |
| 核对数据、隐私和许可证 | [公开边界](PUBLICATION_BOUNDARY.md) · [第三方声明](THIRD_PARTY_NOTICES.md) |
| 理解训练与持续学习边界 | [学习工作台](QUALITY_LEARNING_WORKBENCH.md) · [遗忘验收](CONTINUAL_LEARNING_RETENTION.md) |
| 参与开发 | [贡献指南](../CONTRIBUTING.md) · [开发来源说明](DEVELOPMENT_PROVENANCE.md) |

## 三种运行形态

- **GitHub Pages**：浏览器本地图像取证和独立合成回放；没有业务后端。
- **本地 Web**：React 连接本地 FastAPI，使用账户、项目和持久化数据。
- **Windows 桌面**：Tauri 与本地网关封装同一工作台；能力以具体候选回执为准。

完整在线后端、工厂独立真值、客户 ROI、生产 IAM、数字签名、TTT／RL 策略训练和自动设备写入均不因文档存在而视为已完成。
