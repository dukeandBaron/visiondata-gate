# VisionData Gate 技术路线（小白可读版）

## 一句话理解

VisionData Gate 是一个面向工业视觉算法工程师、质量负责人和数据治理团队的“异常处置 Agent”。用户把换型后的图像、标注、metadata、工单、工艺与视觉方案证据纳入同一个版本化案件后，系统不是只回答一句“哪里有问题”，而是完成证据资格化、竞争假设、动态补证、人工决定、私有派生整改、Child Run 复验和凭证交付的一整条业务流程。

主赛道是 GOAI 赛道二“无界应用 Boundless Agents”；2026-09-02 最新排期为第 03 队、AI+其他，工业视觉 / 制造业是应用领域。项目不是在应用与 Infra 之间二选一：工业异常处置 Agent 承载用户场景，Evidence-first Agent Infra 则通过工具合同、动态调度、失败关闭、上下文交接、证据追踪与 adapter 复用形成技术加分层。

## 为什么需要这个应用

工业视觉换型后出现 NG 异常时，清晰度、曝光、重复图像、跨划分泄漏、标注尺寸、场景覆盖、工艺变更和授权范围等证据通常散落在不同系统。传统做法容易出现三个问题：

1. 证据分散，无法回到同一个案件版本。
2. 证据失效、工艺偏移、视觉方案漂移与真实缺陷形成竞争解释。
3. 问题、人工计划、整改副本和复验结果之间缺少可追踪关系。

VisionData Gate 把这些碎片化动作组织成可运行、可复核、可交付的任务闭环。

## 用户看到的六步闭环

```text
创建异常案件并冻结调查目标
  → 校验来源、合同、权限和工具白名单
  → 五类确定性工具资格化证据
  → Leader 根据证据缺口决定是否补证
  → Policy Judge 形成门禁结论和责任底账
  → 具名人员批准 CAPA，仅在私有派生版本整改
  → Child Run 按同一合同独立复验
  → 交付 Decision Packet、证据矩阵、reason trace 和 Audit Envelope
```

最终交付不是一段聊天内容，而是结构化结果：

- Gate 结论：`PASS`、`RECAPTURE`、`QUARANTINE` 或 `DEFER`；
- findings：问题代码、严重度、样本引用和工具证据；
- work orders：整改动作、原因、优先级和样本范围；
- rule checks：每条门禁规则的通过/失败记录；
- evidence matrix：工具 → finding → 工单 → 规则检查的映射；
- `evidence_span` 与 `reason_trace`：证据片段和推理追踪；
- 交付哈希：用于验证文件未被替换或篡改。

## 系统分为五层

### 1. 产品层

Streamlit 企业工作台提供项目、审核任务、审核记录、能力目录、API 接入、安全权限和评审模式。FastAPI 暴露任务提交、状态、事件、trace 和证据下载接口。工作台与 API 共用同一个服务层和 SQLite 任务存储。

### 2. Agent 编排层

Manager 负责目标与合同校验；Leader 负责拆解任务和依据证据重规划；Workers 调用白名单工具；AI Council 只做有引用的解释和质询；冻结 Policy Judge 拥有门禁裁决权；Repair Operator 只在保留副本上执行允许的工单；Audit Clerk 负责证据交付。

这些角色均为工具与规则驱动的本地确定性 Agent 角色，不是真人专家，也不冒充外部大模型调用。本版本实际模型调用数和模型费用均为 0。

### 3. 工具层

系统固定五类只读检查能力：

- 图像质量：解码、尺寸、曝光和清晰度；
- 重复与泄漏：精确/近似重复、跨划分泄漏；
- 标注完整性：缺失标注、图像与标注尺寸一致性；
- 覆盖矩阵：视角、条件和场景组合是否完整；
- 治理审计：元数据漂移、授权和范围边界。

每个工具具有版本、输入/输出契约、权限范围、失败语义和迁移目标。Worker 不能直接修改发布结论。

### 4. 判断与安全层

Policy Judge 使用冻结规则包，不让角色投票覆盖工具事实。工业 profile 的必需工具缺失、失败或证据不完整会由 `Runtime Invariant Guard` 在 PASS 跃迁前拦截；具名 CAPA 和只读父证据 Child Run 也在执行前生成独立回执。生产写回始终要求真实授权主体，当前本地 `PASS` 只允许批次进入沙箱实验训练池。

守卫固化六条可执行不变量：工业 PASS 的工具/证据完整性、CAPA 具名审批、Child Run 父摘要与只读来源绑定、设备写保护、Agent/系统生产放行禁权、未清责任项下的失败关闭。这里使用的准确术语是 `executable runtime invariant monitoring`；项目没有实现时序逻辑模型检查器，因此不写成 formal verification、vGOAL/VITAMIN 实现或“AAMAS 2025 级验证”。

### 5. 证据与复用层

系统将每次运行写成 canonical JSON/CSV、证据矩阵、事件 trace 和哈希清单。Skills、Tool Contract、AgentTeams adapter 与行业规则包都可独立替换和复用，但替换后必须重放相同 fixture 并通过同一门禁。

## 为什么不是固定流水线

项目先做了一个反证实验：在相同输入、合同、工具和 Judge 下，对传统流水线、单 Agent 和多 Agent 运行 8 seeds × 3 repeats × 4 perturbations × 3 architectures，共 288 条冻结合成记录。三种架构在该协议内的错误放行率均为 0%、任务成功率和扰动稳定率均为 100%、F1 均为 0.96；这些数字不是工厂 KPI。固定 SOP 下，多 Agent 没有质量优势，反而使用更多评审和计算单元。

因此项目不把“角色多”当作创新，而把多 Agent 的必要边界限定为：中间证据改变后续任务。

Omni-180-v1 本地离线固定样本 pilot 中，初始五类工具完成第一轮裁决后出现三类新证据：

- metadata 与文件树数量漂移 15；
- 发现 28 个原生分辨率组；
- 2 个样本出现跨工具处置冲突。

Leader 随后发生 1 次 replan，动态增派 3 个不同 Worker，完成元数据对账、分辨率分组补证和冲突复核，再交给 Judge 复判。最终结论为 `RECAPTURE`，形成 45 条 finding、45 张工单，其中 2 条转 `INVESTIGATE`。

## 三个证据命名空间

| 命名空间 | 分母 | 能证明什么 | 不能证明什么 |
|---|---:|---|---|
| Synthetic-v3 | 12 个注入真值问题 | 整改与同合同复验闭环可运行 | 真实行业效果 |
| ArchBench-v2 | 288 条记录 | 同协议架构对照与负结论 | 多 Agent 普遍优越、客户 ROI、生产 SLO |
| DynamicBench-v2 | 288 条记录 | 冻结 Worker 字典序的选择正确性、顺序不变性、重复稳定性 | 已校准 Active Sensing、工业准确率、端到端性能 |
| Omni-180-v1 | 操作者声明授权的本地离线副本中固定 180 张 | 真实字节上的本地 Gate 与证据触发重规划 | 原始数据可再分发、独立权属认证、客户现场、全量 4,464 张 Gate 认证、生产批准 |

Omni 源树的 4,464 张图像与 1,439 个 mask 只完成结构/解码审计；Policy Gate 的固定分母是 180，二者不能混写。

## 应用与 Infra 如何双向促进

应用层提出真实约束：多工具证据会冲突、问题必须变成工单、整改后必须按原规则复验、交付物必须可核验。这些约束推动后台实现 typed task、动态调度、权限白名单、失败关闭和统一 reason trace。

反过来，可信后台让应用从“给建议”升级为“交付结果”：用户可以看到问题为何产生、由哪个工具发现、触发了哪条规则、分配了什么工单、复验是否使用同一合同。

## AgentTeams 的诚实状态

项目已经提供 AgentTeams v1.2.2 Worker/Team 资源、Skill 分发计划和静态 conformance 校验；静态契约状态为 `PASS`。当前没有 hosted Team/Matrix 原始运行回执，因此 runtime transport 为 `OPEN`，连接状态必须保持 `mapped_not_connected`。这是一条可替换 adapter 路线，不是已连接声明。

## 当前边界

已验证的是本地工程闭环、合成真值实验、同协议架构 benchmark、Omni-180-v1 固定样本 pilot 和脱敏证据交叉哈希。当前不声称原始 Omni 数据可再分发、独立权属认证、真实客户验收、真实工厂部署、生产 IAM、外部大模型调用、完整 Omni 数据集认证、hosted AgentTeams/Matrix 连接或官网提交回执。

学术口径统一为：`A&A-inspired agent-artifact separation`、`evidence-gap-driven deterministic replanning`、`policy-governed` 与 `executable runtime invariant monitoring`。项目没有接入 CArtAgO Runtime，也没有实现完整 BDI 认知架构、概率信念更新或通用形式化验证；相关研究只作为设计启发和后续对照方向。

顶层开源许可证与 NOTICE 必须由权利主体确认；官网上传和平台回执必须由账号持有人完成。
