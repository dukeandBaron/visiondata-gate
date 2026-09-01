# GOAI Competition Evaluation Guide

本文件将赛事评审问题映射到可抽查的本地证明物。它不是自评分，也不预测比赛结果。

| 官方维度 | 评委需要验证 | VisionData Gate 证明物 | 当前边界 |
|---|---|---|---|
| 行业场景价值 25% | 用户、任务、痛点与收益是否明确 | 授权数据源 → Gate → CAPA → 私有派生版本 → Child Run → 责任队列 | 本地场景成立；客户采用、现场 KPI 与 ROI 仍待外部证据 |
| Agent 能力与任务闭环 25% | 理解、规划、调用、交付、验证与异常处理 | Task Plan、五类工具、证据触发 Worker、人工中断/恢复、Frozen Judge、Decision Packet | 本地合同与运行证据；不宣称所有任务都需要多 Agent |
| 产品体验与 Demo 20% | 是否能从零运行并快速看懂闭环 | 工业 Web 工作台、Reviewer Mode、固定 Demo、REST API 与失败分支 | 本地 served UI 已通过 3 轮 × 7 视口、Goal3 Authority 3/3、console 0/0；89.9 秒 Synthetic Fixture Replay 视频及 QA 已冻结，公开 URL 仍由账号持有人执行 |
| 技术实现深度 15% | 架构、状态、测试和复现是否可信 | Typed contracts、ToolTrace、Control Plane、DynamicBench、lineage、Audit Envelope | `PASS_LOCAL_RC3_RELEASE_CANDIDATE`；精确 Full、双构包、clean-extract、Attestation、匹配 clean checkout 与 toolchain 以完整本地验证集为准，第三方复现仍待外部证据 |
| 安全、合规与可追溯 10% | 授权、隐私、幻觉、人工确认和依据 | 只读默认、allowlist、Grounding Guard、人工批准、脱敏 evidence、失败关闭 | 独立法律审查、生产 IAM 与现场验收仍属于外部范围 |
| 开放 / 复用贡献 5% | 是否有接口、示例、文档和许可证 | Apache-2.0、Site Pack、Tool/Rule Contract、Evidence Schema、Adapter SDK、API、SBOM | 本地可复用包已形成；仓库公开与第三方复现仍需要外部回执 |

## 工业方向补充检查

- **多源融合**：图像、标注、metadata、方案、工单、工艺与只读回执进入同一个版本化案件。
- **解释性**：每条 finding 绑定确定性工具结果、evidence span 与规则检查。
- **可操作性**：输出责任队列、整改方案、人工节点和复验条件，而不是只给文本建议。
- **安全红线**：`human_only`、`no_device_control`、`production_release_allowed=false` 是硬边界。

## 使用方法

评审材料应从产品流程自然展示这些证明物。首页只保留产品定位、任务闭环与运行入口；完整分母见 [EVIDENCE_AND_BENCHMARKS.md](EVIDENCE_AND_BENCHMARKS.md)，当前状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)，可声明边界见 [CLAIM_SCOPE.md](CLAIM_SCOPE.md)。
