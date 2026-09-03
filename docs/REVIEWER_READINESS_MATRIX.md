# Reviewer Readiness Matrix｜赛道二应用评审就绪度

本矩阵先按 2026-09-02 最新 9 页指南第 3–5 页的四项复赛重点核验交付，再按此前 20 页官方手册第 14 页的六项权重建立能力索引。最新指南没有重新发布百分比；两套结构不能混写。它不是官方评分，也不预测排名。公开规则摘要与证据入口见 [`GOAI_SEMIFINAL_GUIDE_20260902.md`](GOAI_SEMIFINAL_GUIDE_20260902.md) 和 [`GOAI_SCORE_EVIDENCE_INDEX.md`](GOAI_SCORE_EVIDENCE_INDEX.md)。

## 状态语义

| 状态 | 含义 |
|---|---|
| `PASS` | 当前本地声明存在可复验实现和产物 |
| `PARTIAL` | 本地工程成立，但客户、现场、部署或权利证据未闭合 |
| `OPEN` | 尚无足够证据或真实运行回执 |
| `OWNER_ACTION` | 必须由账号或权利主体完成 |

版本边界：`PASS_LOCAL_RC3_RELEASE_CANDIDATE` 只属于冻结 `source_commit=c5fd68fc38025ffab4345cd739e611c96b13c530`、`source_tree=5501787b6ed452759af16e60dca76ce0c2ec54bf`。RC4 Defense Kit 已取得独立的 `PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY`；公共镜像已取得 `PASS_PUBLIC_RC4_SYNC`，绑定 source commit `46a7242f9aa746f9b8f0f78b776d662422d32c72`、source tree `ab27540b18b8d63db6d9db9256fa2b3330f44dfc`、public head `eb3ef24f7b7df771a4be51a1a3263a060c561db3` 和成功工作流 `33718870200`。本轮 RC5 文档尚未发布，官网提交仍为 `PENDING`。

## 最新指南四项复赛核验

| 复赛重点 | 当前证明物 | 状态 | 不得外推 |
|---|---|---|---|
| 行业场景价值 | 工业视觉数据准入问题、明确角色、Omni 私域离线 Pilot、VisA RC5 公开工业代理正式复验、DynamicBench-v3 合成编排 | `PARTIAL_STRONG` | 客户验收、在线工厂 shadow、生产 KPI、ROI |
| Demo 与应用验证 | 14 个公开路由、60 秒路径、Worker/证据/异常/人工闸门/Child 投影、摘要漂移失败关闭 | `PASS_PUBLIC_SYNTHETIC_REPLAY` | 公开回放等于私域 API、具名批准或生产 PASS |
| 工程与材料可核验性 | Incident v6、typed contract、ToolTrace、Frozen Judge、JCS/SHA、锁文件、GitHub Actions clean checkout/build、RC4 Release | `PASS_LOCAL_ENGINEERING / PASS_PUBLIC_RC4_SYNC` | 内容哈希等于签名、第三方采用或当前 RC5 已发布 |
| 数据与合规边界 | 只读来源、私有派生、公开隐私门、API Key 本机边界、`human_only` | `PASS_LOCAL_BOUNDARY` | 独立权属认证、原始私域数据可再分发、生产授权 |

## 六维矩阵

| 官方维度 | 权重 | 当前核心证据 | 状态 | 仍缺什么 |
|---|---:|---|---|---|
| 行业场景价值 | 25% | 工业视觉数据源授权、批次审核、CAPA/Child；Omni 私域离线 Pilot；VisA RC5 公开工业代理正式复验；DynamicBench-v3；外部标准/论文问题证据 | 问题定义 `PASS_LOCAL`；代表性 `PASS_EXTERNAL_SOURCES_BOUNDED`；客户价值 `PARTIAL_MEASUREMENT`；工厂 shadow `HOLD` | 客户双人/QMS 真值、岗位研究、现场 KPI、运营埋点和生产候选恢复 |
| Agent 能力与任务闭环 | 25% | 计划预览/五项批准绑定；首轮工具任务；中间证据触发 1 replan / 3 Workers / 3 新 ToolTrace；Policy Judge；`_05` 整改→派生版本→child Run→转调查 | `PASS_LOCAL` | 更多行业批次与真实非确定性模型辅助对照 |
| 产品体验与 Demo 完成度 | 20% | 数据源、项目、计划审批、动态补证、风险处置流、候选方案、原子底账、证据下载、Reviewer Mode、API | `PASS_LOCAL_REVIEW_UI_VERIFIED / PASS_LOCAL_VIDEO_QC_CURRENT_PUBLIC_BUILD / PUBLIC_SYNTHETIC_REPLAY` | 最新指南给现场 Demo 1 分钟；当前 57.33 秒视频绑定公开工作台六页与 `3 selected / 2 rejected / 4 hypotheses / 4 gaps`；89.9 秒 RC3 视频仅作历史备用；公共 Pages 只投影经 SHA 校验的合成只读事实 |
| 技术实现深度 | 15% | ArchBench-v2、typed task、Contract-Net 派发、精确 finding 绑定、方案/审批哈希、append-only 审计、同合同 child Run、确定性构包 | 冻结 RC3 `PASS_LOCAL_RC3_RELEASE_CANDIDATE`；RC4 `PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY / PASS_PUBLIC_RC4_SYNC` | GitHub Actions clean checkout/build 已通过；独立终端用户复验和当前 RC5 发布仍待回执 |
| 安全、合规与可追溯 | 10% | fail closed、批准前执行阻断、干预前快照、授权声明、原始数据不复制、脱敏 evidence、prompt-injection 12/12 + 6/6、loopback 4/4、Claim Scope | `PASS_LOCAL_BOUNDARY` | 独立权属/法律审查、外部环境与生产审批回执 |
| 开放/复用贡献 | 5% | Apache-2.0、NOTICE、Skills、Tool Contract、Rule Pack、Evidence Schema、Adapter SDK、API、SBOM | `PUBLIC_SOURCE_AVAILABLE / GITHUB_ACTIONS_CLEAN_BUILD_PASS` | 独立终端用户采用与复用回执仍待取得；RC5 文档尚未发布 |

## 评委建议读取顺序

1. 先读官方规则锚点，确认当前是 Boundless Agents 复赛；最新排期为第 03 队、AI+其他，应用领域为工业视觉，而非 Agent Infra；
2. 先用本地工作台理解目标用户、痛点和真实 API 闭环，再用公共 Pages 核对 `PUBLIC_SYNTHETIC_REPLAY`、manifest 摘要与隐私边界；两者不得互相冒充；
3. 从“数据源”创建项目与审核任务；核对批准绑定，再观察首轮取证、三条动态补证、终裁、3 个风险处置流、3 套候选方案和证据 ZIP；
4. 先分开核对三条证据轨：Omni 私域离线 `4,464/1,439 profile → 固定 180 Gate → 49→33 findings`；VisA RC5 公开工业代理 600-episode 正式复验；DynamicBench-v3 合成编排。三条分母不得合并；
5. 读取 RC3 `_03` 父 Run，核对 4,464 source profile、固定 Gate 分母 180、48→49 原子记录、3 风险流、3 方案、5→8 ToolTrace、1 replan、3 Workers、18-member ZIP 与 27/27 验证；
6. 读取 `_05` CAPA 与 `_06` assessment，核对私有派生 180 图像/60 masks、独立 child Run、6 关闭/43 打开、`TRANSFERRED_TO_INVESTIGATION` 与最小成本 `NOT_ESTIMABLE`；
7. 单独读取冻结 `evidence/submission/vdg-20260816-rc1/`，核对历史公开快照的 45 findings/work orders；不得把 45 与 RC3 的 49 混写；
8. 分别读取 ArchBench-v2 与 DynamicBench-v1：前者是固定 SOP 架构反证，后者是动态触发 P/R；二者不能互借结论；
9. 抽查计划/干预快照，以及工具 → finding → responsibility item → rule check → child recheck 的 `evidence_span`、`reason_trace` 和 SHA-256；
10. 查看运行时加固回执，核对网络 4/4、攻击/良性 12/12 + 6/6、协议 3/3 以及真实后端连接数 0；
11. 查看 `docs/CLAIM_SCOPE.md`，确认客户、生产、4,464 全量 Gate、真实外部模型和 hosted AgentTeams 没有被本地证据升级；最终再核对 RC3 QA 与包外交付回执来自同一候选版本。

## 评审追问与回答锚点

| 追问 | 简短回答 | 证据 |
|---|---|---|
| 这是不是规则脚本？ | 固定检查使用确定性工具；Agent 价值在证据触发后创建新任务，并将结果闭环到工单和复验 | dynamic plan + Canvas |
| 人能否控制 Agent？ | 可在工具调用前审阅/批准/取消计划，运行后确认已审阅或要求修改；操作记录只追加并绑定变更前快照 | task plan + intervention timeline |
| 为什么有 49 条，是否只是工单系统？ | 49 是固定 180 Gate 上逐 finding 的原子证据底账，不是 49 个 Agent 任务；产品上层聚合为 3 个责任处置流和 3 套可比较方案，原子层只用于关闭、追责与复验 | industrial delivery receipt + `_03` verification |
| 方案能否落地？ | 三套方案均给出覆盖、暂缓项、相对 effort、责任波次、残余风险和 Plan SHA；最高覆盖方案已执行到私有派生版本和独立 child Run，但只关闭 6/49，43 条转调查，因此未把 finding 下降写成恢复成功 | `_05` CAPA + `_06` assessment |
| 为什么需要多 Agent？ | ArchBench-v2 在固定 SOP 未显示优势；DynamicBench-v1 中 Dynamic 与单 Agent 质量持平且更慢，但相对固定多 Agent 少 57 次无效补证，因此只在中间证据改变后续任务时使用 | ArchBench-v2 + DynamicBench-v1 |
| 是否用了真实数据？ | 用户对本地 Omni 工业异常检测数据源作授权声明，系统只读 profile 4,464 张并对固定 180 张执行 Gate；这不是客户私有数据、工厂现场验证或独立权属认证 | source authorization + source profile + Omni receipt + Claim Scope |
| 是否用了外部模型？ | 冻结 release 的 actual model calls 为 0；开发分支已通过三类本机协议夹具，但真实 LongCat/VGGT/OmniVGGT 连接数仍为 0 | release manifest + runtime hardening receipts |
| AgentTeams 是否接入？ | v1.2.3 本地 Hosted probe/submission gateway、具名 approval 与不可变回执合同已实现；默认 `NOT_CONFIGURED`，真实远端回执仍 `NOT_PROBED` | Hosted transport API + Integrations / Command Center + runbook |
| PASS 能否生产发布？ | 不能；本地 PASS 只进入沙箱实验训练池，生产写回需真实授权 | GateResult boundary |
| 证据会不会被替换？ | release 与 ZIP 均有 canonical manifest、交叉 SHA-256 和干净解压复核 | release/package receipts |

## 诚实边界

Synthetic-v3、ArchBench-v2、DynamicBench、Omni、VisA、网络、prompt-injection 和后端协议各有独立分母，不能互相借用结论。Omni 4,464 张源树已完成授权声明、只读 profile 与产品任务绑定，但 Policy Gate 只覆盖固定 180；`_05` 的 180 图像/60 masks 是产品私有派生版本，不是公开再分发或物理重采。VisA 只提供程序化跨 split 精确重复治理真值：2026-09-03 已在 RC5 当前环境完成 600-episode 正式复验并返回 `PASS`，Dynamic / Fixed 正确终态均为 `525/600`、unsafe release 均为 0，调用 `2,550 vs 2,700`、不可恢复冗余重试 `0 vs 150`。report semantic SHA-256 为 `1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c`，implementation receipt semantic SHA-256 为 `7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf`。它只证明合同感知效率，不证明 Worker replanning、工厂指标、自然缺陷精度、生产故障率或 ROI。当前公开托管页面仅为 SHA 绑定的 Synthetic Replay；仍没有真实客户验收、在线工厂 shadow、生产部署、真实 LongCat/VGGT/OmniVGGT、hosted AgentTeams/Matrix 或官网提交回执。
