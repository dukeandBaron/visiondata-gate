# GOAI Competition Evaluation Guide

本文件将赛事评审问题映射到可抽查证明物。它不是自评分，也不预测比赛结果。最新 9 页复赛指南先核验四项交付；下方六维权重来自此前 20 页手册，两者不能混写。

## 最新复赛指南：四项优先核验

| 复赛重点 | 当前证明物 | 当前边界 |
|---|---|---|
| 行业场景价值 | 明确用户与工业视觉数据准入任务；Omni 私域离线、VisA RC5 公开工业代理正式复验、DynamicBench-v3 合成编排三轨证据 | 无客户验收、在线工厂 shadow、生产 KPI 或 ROI |
| Demo 与应用验证 | 14 个公开路由、Worker/工具/异常/人工闸门/Child 任务链、摘要漂移失败关闭 | 只读 `PUBLIC_SYNTHETIC_REPLAY`，不连接私域 API 或制造生产 PASS |
| 工程与材料可核验性 | Incident v6、typed contract、ToolTrace、Frozen Judge、JCS/SHA、锁文件、GitHub Actions clean build、RC4 Release | RC4 公共同步 PASS 不等于 RC5 文档已发布或第三方采用 |
| 数据与合规边界 | 来源只读、私有派生、密钥本机保管、隐私门、`human_only` | 操作者授权声明不等于独立权属认证或再分发许可 |

## 此前 20 页手册：六维能力索引

| 官方维度 | 评委需要验证 | VisionData Gate 证明物 | 当前边界 |
|---|---|---|---|
| 行业场景价值 25% | 用户、任务、痛点与收益是否明确 | 授权数据源 → Gate → CAPA → 私有派生版本 → Child Run → 责任队列；Omni/VisA/DynamicBench 分轨证据 | 本地场景成立；客户采用、现场 KPI 与 ROI 仍待外部证据 |
| Agent 能力与任务闭环 25% | 理解、规划、调用、交付、验证与异常处理 | Task Plan、五类工具、证据触发 Worker、人工中断/恢复、Frozen Judge、Decision Packet | 本地合同与运行证据；不宣称所有任务都需要多 Agent |
| 产品体验与 Demo 20% | 是否能从零运行并快速看懂闭环 | 工业 Web 工作台、Reviewer Mode、固定 Demo、REST API 与失败分支 | 本地工作台已验证；RC4 57.33 秒视频绑定当前公开 build；公开 Pages 只投影 SHA 绑定的合成只读事实 |
| 技术实现深度 15% | 架构、状态、测试和复现是否可信 | Typed contracts、ToolTrace、Control Plane、DynamicBench、lineage、Audit Envelope | 冻结 RC3 `PASS_LOCAL_RC3_RELEASE_CANDIDATE`；RC4 `PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY / PASS_PUBLIC_RC4_SYNC`；当前 RC5 文档尚未发布 |
| 安全、合规与可追溯 10% | 授权、隐私、幻觉、人工确认和依据 | 只读默认、allowlist、Grounding Guard、人工批准、脱敏 evidence、失败关闭 | 独立法律审查、生产 IAM 与现场验收仍属于外部范围 |
| 开放 / 复用贡献 5% | 是否有接口、示例、文档和许可证 | Apache-2.0、Site Pack、Tool/Rule Contract、Evidence Schema、Adapter SDK、API、SBOM | 公共镜像已提供源码并通过 GitHub Actions clean checkout/build；独立终端用户复用仍需外部回执 |

VisA 只使用程序化跨 split 精确重复作为治理真值。2026-09-03 已在 RC5 当前环境完成 300 clean + 300 programmatic block 正式复验并返回 `PASS`：Dynamic / Fixed 正确终态均为 `525/600`、unsafe release 均为 `0`、瞬时恢复均为 `150/150`；工具调用 `2,550 vs 2,700`，不可恢复故障冗余重试 `0 vs 150`。report semantic SHA-256 为 `1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c`，implementation receipt semantic SHA-256 为 `7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf`。该结果只证明合同感知效率，不证明 Worker replanning、工厂指标、自然缺陷检测精度、真实故障分布或客户 ROI。

## 工业方向补充检查

- **多源融合**：图像、标注、metadata、方案、工单、工艺与只读回执进入同一个版本化案件。
- **解释性**：每条 finding 绑定确定性工具结果、evidence span 与规则检查。
- **可操作性**：输出责任队列、整改方案、人工节点和复验条件，而不是只给文本建议。
- **安全红线**：`human_only`、`no_device_control`、`production_release_allowed=false` 是硬边界。

## 使用方法

评审材料应从产品流程自然展示这些证明物。首页只保留产品定位、任务闭环与运行入口；完整分母见 [EVIDENCE_AND_BENCHMARKS.md](EVIDENCE_AND_BENCHMARKS.md)，当前状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)，可声明边界见 [CLAIM_SCOPE.md](CLAIM_SCOPE.md)。
