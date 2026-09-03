# GOAI 2026 赛道二复赛指南核验｜2026-09-02

> 本文件记录组委会最新 9 页复赛指南中的可公开事实，用于约束答辩与附件包装。它不替代组委会后续通知、腾讯会议通知或官方平台回执。

## 来源身份

- 文件名：`GOAI_2026_赛道二_无界应用_Boundless_Agents_复赛参赛指南 Semi-Final Participation Guide.pdf`
- 标题：`赛道二｜无界应用 Boundless Agents｜复赛参赛指南`
- 页数：9
- SHA-256：`213caa8af21c468767eacbcb0fd21640e26cd838d2c34c90434fe16ca23d326b`
- 核验日期：2026-09-02
- 权威边界：会议链接、会议号、密码和最终排期以组委会最新通知为准（第 1、5 页）。

## VisionData Gate 固定答辩排期

| 项目 | 最新指南明文 |
|---|---|
| 队伍 | 第 03 队 |
| 赛题方向 | `AI+其他 / AI + Others` |
| 作品名称 | VisionDataGate |
| 答辩日期 | 2026-09-05 |
| 正式答辩 | 09:16–09:24 |
| 候场要求 | 08:56 前进入候场区 |
| 会议方式 | 腾讯会议；连接信息以组委会通知为准 |

来源：指南第 1、5、6 页。

最新排期把 VisionData Gate 列在 `AI+其他`。因此当前答辩封面、公开首页和报名补充材料统一写为：

```text
赛道二｜无界应用 Boundless Agents
官方排期方向：AI+其他
应用领域：工业视觉数据治理 / 制造业
```

`AI+工业制造` 可作为项目应用领域或历史手册分类，不再冒充本次在线排期中的官方赛题方向。

## 8 分钟答辩合同

| 环节 | 时长 | VisionData Gate 执行合同 |
|---|---:|---|
| 项目陈述 | 3 分钟 | 只回答真实问题、Agent 为什么必要、产品如何闭环、证据和边界 |
| Demo | 1 分钟 | 输入范围 → Agent/工具 → 结果 → 异常处理 → Child 效果复验 |
| 评委问答 | 3 分钟 | 先答结论，再给证据路径与不能外推的边界 |
| 独立评分与切换 | 1 分钟 | 停止操作，不占用下一队时间 |

来源：指南第 1 页。原 89.9 秒视频保留为完整备用记录；现场主 Demo 必须按 60 秒路径执行。

## 复赛硬性要求

指南第 2–5 页把复赛核心收敛为六个可核验结果：

1. 项目完成度；
2. Demo 可运行性；
3. 用户流程闭环；
4. 技术实现；
5. 数据与合规说明；
6. 开放 / 复用规范。

作品还必须面向真实、明确的行业场景，具备 Agent 能力，并至少完成一条可验证的端到端任务链。评委必须能够访问代码、工程材料、Demo 与运行证据；高风险场景必须写清风险提示和人工确认边界。

## 四项提交材料

| 官方材料 | 指南要求 | VisionData Gate 当前对应物 |
|---|---|---|
| 更新版项目方案 PPT/PDF | 更新场景、产品流程、Agent 架构、数据来源、工具、风险、指标和落地计划 | `GOAI_VisionDataGate_Semifinal_Defense_RC4_20260902.pptx/.pdf` |
| 可运行 Demo 或 Demo 视频 | 输入、Agent 处理、工具/知识调用、结果交付、异常处理和效果验证 | 公开只读工作台 + 本地工作台 + 60 秒备用剪辑 |
| 代码仓库或等价工程材料 | 运行入口、依赖、配置、示例数据、部署、测试和运行证据 | GitHub 公共镜像、README、锁文件、合成样本与验证脚本 |
| 数据来源与合规说明 | 类型、来源、授权、脱敏、隐私、行业风险与不替代专业决策 | `DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md` 与公开边界文档 |

来源：指南第 3、4 页。

## Demo 完整任务链合同

指南第 4 页要求 Demo 至少出现以下六段，任何一段缺失都不能只靠口播补齐：

```text
用户输入
→ Agent 处理
→ 工具或知识库调用
→ 结果交付
→ 异常处理
→ 效果验证
```

VisionData Gate 的 60 秒公开路径对应为：

```text
冻结合成案件范围
→ Worker 选择与六阶段处理
→ triggering evidence / 确定性工具回执
→ Parent / Child disposition 与证据清单
→ FAIL_CLOSED_THEN_RECHECKED
→ Child 同合同复验 + production=false
```

公开路径只证明 `PUBLIC_SYNTHETIC_REPLAY` 的可复现任务链，不代表客户验收、工厂 shadow、生产部署或正式放行。

## 评审重点与旧权重的关系

最新 9 页指南第 5 页列出四个评审重点，但没有再次给出百分比：

- 行业场景价值；
- Demo 与应用验证；
- 工程与材料可核验性；
- 数据与合规边界。

此前 20 页官方手册第 14 页给出的六维权重仍作为评分对齐依据：行业场景 25%、Agent 闭环 25%、产品 Demo 20%、技术 15%、安全合规 10%、开放复用 5%。两份材料的关系是“旧手册提供权重，新指南强化复赛交付与答辩核验”，不能把新指南写成重新发布了同一组权重。

## 当前状态边界

```text
current_rc4_defense_kit=PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY
public_mirror_rc4_sync=PENDING
frozen_rc3_candidate=PASS_LOCAL_RC3_RELEASE_CANDIDATE
frozen_rc3_source_commit=c5fd68fc38025ffab4345cd739e611c96b13c530
frozen_rc3_source_tree=5501787b6ed452759af16e60dca76ce0c2ec54bf
official_submission=PENDING
official_evaluation=NOT_EVALUATED
factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION
production_release_allowed=false
machine_write_permitted=false
authority=human_only
```

冻结 RC3 的 PASS 只绑定上述 commit/tree。当前 RC4 的 PPT/PDF、当前公开工作台 57.33 秒备用视频、公共源码快照和 Defense Kit 已取得独立的 `PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY`，没有从 RC3 继承 PASS；GitHub 公共镜像 RC4 同步与官网提交仍分别保持 `PENDING`。

答辩排期确认不等于官网提交完成；公开工作台可访问不等于工厂验证；Child 的本地合成结果不等于生产放行。
