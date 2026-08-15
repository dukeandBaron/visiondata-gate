# VisionData Gate｜工业视觉数据治理与发布 Agent

**GOAI 赛道二：无界应用 Boundless Agents · AI+工业制造**  
Release：`vdg-20260816-rc1`

## 解决什么问题

工业视觉图像进入训练或评测前，需要同时检查质量、重复/泄漏、标注、覆盖和治理边界。现有脚本通常只给碎片化报告，无法处理跨工具冲突，也难以把问题稳定地转成整改工单并按同一规则复验。

VisionData Gate 面向视觉算法工程师和工业数据治理团队，把批次审核做成可运行的 Agent 应用：任务理解 → 并行检查 → 证据触发补证 → Policy Gate → 整改工单 → 保留副本修复 → 同合同复验 → 证据交付。

## 用户得到什么

- 结构化 Gate 结论与明确边界；
- finding 到 work order 的一一追踪；
- `evidence_span` 与 `reason_trace`；
- 同规则复验结果；
- GateResult、证据矩阵、事件 trace 和 SHA-256 凭证；
- 工作台、REST API 和 SaaS/流水线嵌入接口。

## 已完成到哪一层

| 证明层级 | 状态 | 可核验事实 |
|---|---|---|
| 已工程实现 | `PASS` | 工作台、API、五类工具、Dynamic Leader、Frozen Policy Judge、工单、同合同复验和证据包已接入本地闭环 |
| 已公开数据实跑 | `PASS` | 固定 180 张公开图像触发 1 次 replan、3 个动态 Worker、45 条 findings/工单，最终 `RECAPTURE` |
| 下一阶段外部验收 | `OPEN` | 客户 shadow test、工厂只读接入、生产 IAM/部署和 hosted transport 需要外部主体回执 |

前两层说明“项目已经做成并在固定公开数据上跑通”；第三层说明“下一步如何扩大采用范围”，不是对前两层的否定。可机读证明为 `scenario_delivery_receipt.json`。

## 为什么需要 Agent

项目先做同协议反证：传统流水线、单 Agent、多 Agent在 288 条固定 SOP 记录上错误放行率均为 0%、成功率/扰动稳定率均为 100%、F1 均为 0.96，因此不声称“多角色天然更好”。

真正的 Agent 边界是中间证据改变后续任务。Omni-180-v1 固定公开样本 pilot 中，系统发现 metadata 数量漂移 15、28 个原生分辨率组和 2 个跨工具冲突样本；Leader 随后 1 次 replan、动态增派 3 个 Worker，复判后交付 `RECAPTURE`、45 条 finding 和 45 张工单。

## 技术路线

```text
Streamlit / REST API
  → Manager（目标、合同、权限）
  → Leader（静态工具波次 + 证据触发重规划）
  → 5 类只读 Workers / Tool Gateway
  → AI Council（有引用的解释与质询，建议权）
  → Frozen Policy Judge（唯一门禁裁决权）
  → Repair / Recheck / Evidence Delivery
```

应用层负责真实用户流程；可信 Infra 后台负责 typed task、工具白名单、失败关闭、统一追踪和 adapter 复用。

## 可核验证据

| 命名空间 | 分母 | 已验证结果 |
|---|---:|---|
| Synthetic-v3 | 12 个注入真值问题 | 初始整改、修复后同合同通过，F1 1.00 |
| ArchBench-v2 | 288 条记录 | 三架构同质量；固定 SOP 不支持多 Agent 必要性 |
| Omni-180-v1 | 180 张公开图像 | 1 replan、3 动态 Worker、45 findings/工单、8 rule checks PASS |

## 运行边界与下一阶段

本版本以 `local-deterministic` Runtime 完成上述应用闭环，actual model calls 与模型费用为 0。Omni 源树 4,464 张图像只完成结构/解码审计，Policy Gate 的已验证分母为 180。AgentTeams 静态契约为 `PASS`；将当前闭环扩展到客户、工厂、生产 IAM、全量 Omni、外部 LLM 或 hosted transport 时，需补相应外部验收回执，连接状态暂保持 `mapped_not_connected`。

顶层 LICENSE/NOTICE 需由权利主体确认；官网上传和平台回执需由账号持有人完成。
