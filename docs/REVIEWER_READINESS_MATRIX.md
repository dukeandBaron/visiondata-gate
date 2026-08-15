# Reviewer Readiness Matrix｜赛道二应用评审就绪度

本矩阵将“行业场景价值、Agent 闭环、产品体验、技术复现、安全合规与开放复用”转换成可导航证据。它不是官方评分，也不预测排名。

## 状态语义

| 状态 | 含义 |
|---|---|
| `PASS` | 当前本地声明存在可复验实现和产物 |
| `PARTIAL` | 本地工程成立，但客户、现场、部署或权利证据未闭合 |
| `OPEN` | 尚无足够证据或真实运行回执 |
| `OWNER_ACTION` | 必须由账号或权利主体完成 |

## 五维矩阵

| 维度 | 当前核心证据 | 状态 | 仍缺什么 |
|---|---|---|---|
| 行业场景价值 | 工业视觉批次审核、整改和复验闭环；工作台与 API | `PARTIAL` | 真实用户访谈、授权 shadow test、现场 KPI |
| Agent 能力与任务闭环 | 5 个静态工具任务；Omni 证据触发 1 replan / 3 Workers；Policy Judge 与工单 | `PASS`（本地/固定 pilot） | 更多行业批次与非确定性模型辅助对照 |
| 产品体验与 Demo | 公网评委站点、企业工作台、Reviewer Mode、Canvas、项目/任务/记录/API/权限 | `PASS`（公网静态评委入口 / 本地完整 Runtime） | 完整 Runtime 外部托管与真实用户可用性测试 |
| 技术深度与复现 | ArchBench-v2、typed task、tool contract、reason trace、同合同复验、确定性构包 | `PASS` | 独立环境/第三方复现回执 |
| 安全、合规与开放复用 | fail closed、Claim Scope、redaction receipt、Apache-2.0、NOTICE、Skills、SBOM、AgentTeams adapter | `PASS_WITH_EXTERNAL_BOUNDARY` | 真实数据书面授权与 hosted transport 仍属外部阶段 |

## 评委建议读取顺序

1. 打开 <https://dukeandbaron.github.io/visiondata-gate/>，先看目标用户、痛点、六步闭环和动态重规划 Canvas；
2. 看 Dynamic Leader Canvas，确认初始工具波次后才出现三条动态分支；
3. 读取 `evidence/submission/vdg-20260816-rc1/dynamic_leader_plan.json`，核对每个 task 的 `dispatch_basis=intermediate_evidence` 和 `planned_before_initial_evidence=false`；
4. 读取同目录 `omni_gate_receipt.json`，核对固定 180、1 replan、3 Workers、45 findings/work orders 和交叉 SHA-256；
5. 读取 `architecture_benchmark.json`，核对 288 条记录和 `fixed_sop_multi_agent_necessity_supported=false`；
6. 读取 GateResult 与 evidence matrix，抽查工具 → finding → work order → rule check → recheck；
7. 运行 `tools/check_release_consistency.py`，确认公开 release 无缺失或篡改；
8. 查看 `docs/CLAIM_SCOPE.md`，确认客户、生产、全量 Omni、外部 LLM 和 hosted AgentTeams 没有被本地证据升级；
9. 查看最终 QA 和包外交付回执，确认测试、PPT/PDF、ZIP 和哈希来自同一 release。

## 评审追问与回答锚点

| 追问 | 简短回答 | 证据 |
|---|---|---|
| 这是不是规则脚本？ | 固定检查使用确定性工具；Agent 价值在证据触发后创建新任务，并将结果闭环到工单和复验 | dynamic plan + Canvas |
| 为什么需要多 Agent？ | 288 条固定 SOP 未显示优势，因此只在中间证据改变后续任务时使用 | ArchBench-v2 + Omni-180-v1 |
| 是否用了真实数据？ | 使用公开图像固定样本 pilot；不是客户私有工业数据或现场验证 | Omni receipt + Claim Scope |
| 是否用了外部模型？ | 本版本 actual model calls 为 0；角色是工具与规则驱动的本地确定性 Agent 角色 | release manifest |
| AgentTeams 是否接入？ | 静态 v1.2.2 契约 PASS，runtime transport OPEN，状态 `mapped_not_connected` | conformance + runbook |
| PASS 能否生产发布？ | 不能；本地 PASS 只进入沙箱实验训练池，生产写回需真实授权 | GateResult boundary |
| 证据会不会被替换？ | release 与 ZIP 均有 canonical manifest、交叉 SHA-256 和干净解压复核 | release/package receipts |

## 诚实边界

Synthetic-v3、ArchBench-v2、Omni-180-v1 分母固定且不能互相借用结论。Omni 4,464 张源树只完成结构/解码审计，Policy Gate 只覆盖 180。当前没有真实客户验收、生产部署、外部 LLM、hosted AgentTeams/Matrix 或官网提交回执。钉钉回放无画面时不将其描述为已核验视觉演示。
