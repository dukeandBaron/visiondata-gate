# GOAI 赛道二“无界应用”要求矩阵

官方方向：Boundless Agents · AI+工业制造。状态定义：

- `PASS`：当前工作区存在可复验实现与证据；
- `PARTIAL`：本地工程成立，但外部客户、部署或权利证据未闭合；
- `OPEN`：尚无足够证据；
- `OWNER_ACTION`：必须由账号或权利主体完成。

| 评审关注 | VisionData Gate 对应设计 | 证据入口 | 状态 | 禁止外推 |
|---|---|---|---|---|
| 行业场景价值 | 工业视觉批次进入实验训练池前的质量、泄漏、标注、覆盖与治理审核 | 工作台、API、场景交付凭证、one-pager | `PASS`（本地场景）/ `OPEN`（外部采用） | 已被企业采用、已有 ROI |
| 目标用户 | 视觉算法工程师、数据工程师、数据治理负责人 | 表单文案、Reviewer Mode、完整任务触发 | `PASS`（角色/流程定义）/ `OPEN`（用户研究） | 已完成真实用户研究 |
| 真实任务闭环 | 目标/合同 → 工具 → 动态补证 → Gate → 工单 → 修复 → 同合同复验 → 证据交付 | Runtime trace、GateResult、evidence matrix | `PASS`（本地） | 真实产线已自动闭环 |
| 任务理解 | 严格数据合同冻结目的、阈值、覆盖与发布范围 | `BatchContract`、Pydantic 失败测试 | `PASS` | Agent 可猜测未知字段 |
| 工具调用 | 质量、重复/泄漏、标注、覆盖、治理五类只读工具 | ToolTrace、稳定 finding codes、工具合约 | `PASS` | AI 自行生成测量事实 |
| 动态 Agent 能力 | 首次裁决后根据 metadata 漂移、分辨率组与跨工具冲突增派 Worker | `dynamic_leader_plan.json`、Reviewer Canvas | `PASS`（Omni-180-v1） | 所有任务都需要动态多 Agent |
| 工单与结果交付 | finding → work order → rule check → recheck，带 `evidence_span` / `reason_trace` | `evidence_matrix.csv`、GateResult | `PASS` | 工单等于现场已执行 |
| 多轮/流程交互 | 用户创建任务、查看状态、问题、工单、证据并重新验证 | Streamlit、FastAPI、SQLite | `PASS`（本地） | 生产 SaaS 已上线 |
| 产品体验与 Demo | 企业工作台、在线评委网站、Reviewer Mode、Canvas、三类接入方式 | `website/`、`app.py`、AppTest、视频 | `PASS`（本地与静态网站） | 网站等于生产 SaaS或客户验收 |
| 场景完成证明 | “工程实现→公开数据实跑→外部验收”三级证据 | `scenario_delivery_receipt.json`、Reviewer Mode 下载入口 | `PASS`（前两层） | 第三方验收已完成 |
| 工程深度 | typed task、工具网关、失败关闭、反事实/扰动检查、确定性序列化 | 源码、测试、ArchBench-v2 | `PASS` | 本地时延等于生产 SLO |
| 工程可复现 | `uv.lock`、固定 seed、canonical JSON、确定性 ZIP、clean extract | 最终 QA 与交付回执 | 最终构包后判定 | 合成内测等于真实工业性能 |
| 安全与合规 | 白名单工具、只读默认、生产授权阻断、隐私扫描、SHA-256 | Claim Scope、redaction receipt、package audit | `PASS`（本地边界） | 数据天然已授权、法律认证 |
| 开放复用 | Skills、Tool Contract、规则包、API、AgentTeams adapter | `skills/`、`TOOLS_AND_MCP_CONTRACT.md` | `PARTIAL` | 已形成外部生态贡献 |
| AgentTeams | v1.2.2 Worker/Team CR、Skill 分发、真实回执防伪 | conformance receipt、runbook | 静态 `PASS` / transport `OPEN` | hosted Matrix 已连接 |
| 开源许可证 | SBOM 与第三方许可证元数据 | SBOM、license inventory | `OWNER_ACTION` | 顶层许可已获授权 |
| 官网提交 | 简介、PPT/PDF、候选包与可选视频 | 本地 deliverables | `OWNER_ACTION` | 已上传、已晋级或获奖 |

## 评审信号对应证据

### 1. 行业场景价值

应用聚焦“工业视觉数据批次审核与发布”，不是泛聊天、单点问答或简单内容生成。用户能够提交任务、接收结构化整改工单、按同一规则复验并下载证据包。

### 2. Agent 能力与任务闭环

固定 SOP 下不滥用多 Agent。ArchBench-v2 的 288 条记录显示三架构质量相同；Omni-180-v1 则直接证明中间证据触发一次 replan 和三个新 Worker。这一正负证据共同定义 Agent 的必要边界。

### 3. 产品体验与 Demo 完成度

在线评委网站先展示行业任务、固定公开运行和证据触发 Canvas；本地工作台提供项目、审核任务、历史记录、能力目录、API 和安全权限。Reviewer Mode 将任务闭环、动态规划、benchmark 和边界集中到一个入口，API 可供企业 Agent、SaaS 与流水线调用。

### 4. 技术实现与工程复现

严格 schema、工具合约、冻结 Judge、event/context/skill receipts、同合同复验、canonical evidence、交叉哈希和确定性构包形成可复算链路。最终测试计数只从 `release_manifest.json` 和最终 QA 读取，不在多处硬编码。

### 5. 安全、合规与开放复用

本地 `PASS` 只进入沙箱实验训练池；生产写回阻断。公开 evidence 不含原图、mask、类别名、原文件名或私有路径。Skills、工具接口、规则包和 adapter 可复用；顶层许可证需权利主体确认。

## 三组证据

- Synthetic-v3：12 个注入真值问题，验证整改和同合同复验；
- ArchBench-v2：288 条同协议记录，固定 SOP 不支持多 Agent 必要性；
- Omni-180-v1：固定 180 张公开图像，1 replan、3 dynamic Workers、45 findings/work orders、8 rule checks PASS，最终 `RECAPTURE`。

Omni 源树 4,464 张图像与 1,439 个 masks 只完成结构/解码审计，不写成全量 Policy Gate。

## 对外说明顺序

先说明“已工程实现”的应用闭环，再说明“已公开数据实跑”的固定分母结果，最后将客户、工厂和生产环境列为“下一阶段外部验收”。不再用一串负面免责声明代替成果陈述；同时仍不把本地证据升级成第三方背书。

## 上传前仍需闭合

1. 最终全量测试、Ruff、compileall、PPT/PDF 视觉 QA 和候选 ZIP clean-extract 审计；
2. 由权利主体确认顶层 LICENSE 与 NOTICE；
3. 由账号持有人在赛道二页面上传材料并保存作品 ID 与平台回执；
4. 如进入复赛，再补真实用户访谈、授权工业 shadow test 与 hosted AgentTeams transport 回执；这些不是初赛本地工程已完成项。
