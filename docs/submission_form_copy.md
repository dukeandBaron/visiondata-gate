# GOAI 赛道二初赛提交表单文案

## 基本信息

- 作品名称：VisionData Gate｜工业视觉数据治理与发布 Agent
- 参赛赛道：赛道二“无界应用 Boundless Agents”
- 行业方向：AI+工业制造
- Release：`vdg-20260816-rc1`
- 项目形态：可运行本地应用 + 在线评委 Demo + REST API + 可复现证据包

## 500 字以内作品简介

VisionData Gate 是面向工业视觉算法工程师和数据治理团队的数据批次审核 Agent，已完成本地可运行闭环：理解审核目标与合同，并行调用图像质量、重复/泄漏、标注、覆盖和治理五类只读工具；Leader 依据中间证据动态补证、增派 Worker 或转调查，Frozen Policy Judge 生成门禁结论和整改工单，修复后按同一合同复验，交付 GateResult、证据矩阵、reason trace 与 SHA-256 凭证。在线评委 Demo 展示固定公开运行，工作台与 REST API 可供团队、企业 Agent、SaaS 和流水线调用。Omni-180-v1 固定 180 张公开图像已完成 Policy Gate，触发 1 次重规划、3 个动态 Worker、45 条 finding/工单并判定 RECAPTURE。288 条同协议实验进一步排除固定 SOP 下滥用多 Agent。客户 shadow test、工厂接入和生产部署作为下一阶段外部验收，不影响当前工程实现与公开数据实跑结论。

## 目标用户与场景

目标用户是工业视觉算法工程师、数据工程师和数据治理负责人。典型任务是：一个新的图像与标注批次准备进入实验训练池，需要在固定合同下完成质量、泄漏、标注、覆盖和治理审核，并将问题转成可执行工单，修复后重新验证。

## 场景痛点

1. 多个检查脚本输出分散，缺少统一结论；
2. 同一样本可能被不同工具给出冲突处置；
3. finding、规则、工单和复验结果无法一一追踪；
4. 证据缺失时容易被人工经验或模型解释推测性放行；
5. 结果难以通过 API 交付给企业 Agent、SaaS 或 CI 流水线。

## 任务闭环

```text
用户提交批次和审核目标
→ Manager 校验合同、场景、权限
→ Leader 调度五类工具 Worker
→ 首次 Judge 形成中间证据
→ 证据异常触发动态补证/对账/冲突复核
→ Judge 复判并生成整改工单
→ 保留副本修复
→ 同合同复验
→ 交付结构化结论与证据包
```

## Agent 设计

- Manager：审核目标、合同、范围和权限；
- Leader：拆解静态任务，并根据中间证据动态重规划；
- Workers：调用质量、重复、标注、覆盖、治理工具；
- AI Council：基于证据引用解释、质询和披露限制，只有建议权；
- Policy Judge：应用冻结规则，拥有唯一门禁裁决权；
- Repair/Audit Operators：在保留副本上执行允许的工单，并交付证据。

全部角色为工具与规则驱动的本地确定性 Agent 角色，不是真人专家。本版本 actual model calls 和模型费用均为 0；后续外部模型只能作为非权威解释器接入，不能覆盖工具事实或 Policy Judge。

## 核心创新

1. **证据触发而非固定 DAG**：完成第一轮工具与裁决后，Leader 根据 metadata 漂移、原生分辨率组和跨工具冲突创建新的补证任务。
2. **反证式架构选择**：ArchBench-v2 的 288 条同协议记录没有支持固定 SOP 多 Agent 必要性，项目明确保留负结论。
3. **从 finding 到复验的统一追踪**：工具、finding、工单、rule check、`evidence_span` 和 `reason_trace` 一一映射。
4. **正确失败**：工具缺失、证据不完整、冲突未解决或越权请求会 `DEFER`/`RECAPTURE`，不会推测性放行。
5. **应用与 Infra 双向促进**：面向真实审核任务的闭环提出动态调度和追踪要求；可信后台让应用交付可采用、可复核的结果。

## 数据与实验

- Synthetic-v3：12 个注入真值问题，验证整改与同合同复验，F1 1.00；
- ArchBench-v2：8 seeds × 3 repeats × 4 perturbations × 3 architectures = 288 条记录；三架构错误放行率 0%、成功率与扰动稳定率 100%、F1 0.96；
- Omni-180-v1：固定 180 张公开图像完成 Policy Gate；1 次 replan、3 个动态 Worker、45 findings、45 work orders、8 rule checks PASS，结论 `RECAPTURE`。

Omni 源树 4,464 张图像和 1,439 个 masks 只完成结构/解码审计，不写成全量 Gate。公开 release 不包含原图、mask、类别名、原文件名和私有绝对路径。

## 技术与部署

- Python 3.12、Pydantic、NumPy、Pillow；
- Streamlit 企业工作台与 Reviewer Mode Canvas；
- FastAPI REST API 与 SQLite 本地任务存储；
- canonical JSON/CSV、evidence ZIP 和 SHA-256；
- AgentTeams v1.2.2 静态资源和连接回执防伪门禁；
- `uv.lock`、pytest、Ruff、compileall 和确定性构包。

当前部署模式为本机可运行候选，不是生产 SaaS。工作台和 API 可演示三类接入：团队操作、企业 Agent 调用、SaaS/流水线嵌入。

## 安全、合规与开放复用

- 本地 `PASS` 只进入沙箱实验训练池；生产写回需要真实授权主体；
- 工具白名单、只读默认、失败关闭和证据哈希；
- 公开 evidence 经过结构校验、交叉哈希和私有路径扫描；
- Skills、Tool Contract、规则包和 AgentTeams adapter 可独立复用；
- 代码按 Apache-2.0 开源，NOTICE、第三方声明和 SBOM 随 RC2 交付；该许可不覆盖外部数据、模型或客户资产。

## 三级证据状态

- **已工程实现 `PASS`**：工作台、在线评委 Demo、API、五类工具、动态 Leader、Policy Judge、工单、同合同复验和证据包已接入；
- **已公开数据实跑 `PASS`**：Omni-180-v1 固定 180 张图像完成 Gate，动态分支、finding、工单和规则检查均有交叉哈希凭证；
- **下一阶段外部验收 `OPEN`**：客户 shadow test、工厂接入、生产 IAM/部署、外部 LLM、全量 Omni Gate、hosted AgentTeams/Matrix 与官网提交需对应外部回执。AgentTeams 静态契约已 `PASS`，当前 transport 为 `OPEN`、连接状态为 `mapped_not_connected`。
