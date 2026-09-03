# Claim Scope｜三级证据与对外用词

本文件规定 VisionData Gate 的对外陈述边界。README、PPT、视频、UI 和答辩都应先陈述已完成事实，再说明外部验收范围；不得把本地证据扩大成第三方背书。

## 第一层：已工程实现 `PASS`

- 本地 Runtime 已接通合同校验、五类工具检查、证据触发 Dynamic Leader、Frozen Policy Judge、责任队列、CAPA 方案选择/批准、私有派生版本、同合同 child Run 复验和证据交付；
- Streamlit 工作台、Reviewer Mode、静态评委网站、REST API、CLI 和 canonical evidence package 均有实际代码与测试；
- 当前开发分支新增模型引用/数值/权限 Grounding Guard、CVAT/FiftyOne 整改往返合同与企业验收 Scorecard；这些属于本地工程与合同验证，不等于外部服务已连接；
- 当前开发分支新增安全 HTTP transport、prompt-injection 预检、LongCat/VGGT/OmniVGGT 连接合同及三类运行时回执；loopback 网络固定集为 `PASS_LOCAL`（4/4），prompt-injection v2 为 `PASS_LOCAL_FIXED_ATTACK_SET`（攻击 12/12、良性 6/6），三后端协议夹具为 `PASS_LOCAL_CONTRACTS_ONLY`（3/3）；
- 上述后端夹具只写 `CONTRACT_CONNECTED_LOCAL_TEST`。真实 LongCat/VGGT/OmniVGGT 权重、服务与工业效果仍为 `NOT_TESTED` / `REAL_BACKEND_NOT_CONNECTED`；省略可选后端时编排层仍可写 `OPTIONAL_BACKEND_NOT_CONNECTED`；
- finding、原子 work order、风险处置流、候选方案、rule check、`evidence_span`、`reason_trace` 和 SHA-256 形成统一追踪链；聚合层不删除原子证据；
- 换型后异常案件 v5 已实现可校验的确定性专业 Worker、竞争性假设与证据边、规划 Belief Ledger、Worker Selection、进展/停滞账本、唯一人工决定、精确 CAPA、决定单次消费、不可变 child case 和阶段事件哈希链；这是本地产品闭环，不是分布式 Agent 平台或生产现场验证；
- Synthetic-v3 在 12 个注入真值问题上验证初始 `RECAPTURE`、修复后 `PASS` 与 F1 1.00；这属于合成工程闭环证据。

## 第二层：已授权工业数据产品实跑 `PASS_LOCAL_AUTHORIZED_RUN`

- 冻结 RC2 脱敏证据快照 `Omni-180-v1`：操作者声明授权的本地离线副本中固定 180 张、1 次 replan、3 个动态 Worker、45 条 findings/工单、8 项规则检查，结论为 `RECAPTURE`；该称谓不代表原始图像具备公开再分发许可；
- 当前 RC3 本地产品运行：操作者对 Omni 本地数据源作授权声明，系统完成 4,464 张图像/1,439 个 masks/30 类的只读 source profile，并将固定 180 张送入 Gate；原始资产未复制进项目或证据包；
- RC3 `_03` 首次裁决 48 条 findings/原子记录与 5 个 ToolTrace；中间证据触发 1 次 replan、3 个动态 Worker 与 3 个新 ToolTrace；最终 49 条 findings/原子记录、8 个 ToolTrace，结论为 `RECAPTURE`；
- 49 条不是 49 个 Agent 任务：系统保留 49/49 精确 source-finding 绑定的底账，同时聚合为 3 个风险处置流（2 条证据调查、7 条数据划分治理、40 条采集质量恢复）和 3 套候选方案（3/49、47/49、49/49）；任何方案都不直接授予 PASS；
- RC3 `_05` 真实执行 49/49 最高覆盖方案：父来源保持只读，在产品私有目录复制 180 图像/60 masks 形成派生版本并创建独立 child Run；findings 49→33，但只有 6 条责任项证实关闭、43 条仍打开，终态 `TRANSFERRED_TO_INVESTIGATION`，`recovery_success=false`；
- RC3 `_06` 将三套冻结方案与 `_05` 唯一实跑结果绑定。当前授权候选池未观察到可发布方案，最小恢复成本为 `NOT_ESTIMABLE`；另外两套未执行方案没有成功率、工时、金额或 ROI；
- 当前 RC3 授权产品事件 18 条，人工生产授权保持 `pending`；含审批绑定、工业交付和方案回执的 18-member Evidence ZIP SHA-256 为 `17631D2F9FA51E58D8DECDB13E4E9EF91F9D2119E2BBA344E51DB78F5F455098`；
- 独立验证 27/27 `PASS`，新增覆盖审批四重绑定、精确 finding 关联、风险流与方案哈希、child Run 末波、来源注册库只读不漂移；原图/私有路径排除、可选模型未连接和人工权限边界继续通过；
- ArchBench-v2 含 288 条冻结合成同协议记录。三种架构在该协议内的错误放行率均为 0%、成功率与扰动稳定率均为 100%、F1 均为 0.96，因此固定 SOP 下多 Agent 必要性未被支持；这些数字不能外推为工厂误放行率；
- DynamicBench-v1 含 4 架构 × 24 fixtures × 3 repeats = 288 records；Dynamic Leader 触发 P/R 为 1.0/1.0，相对固定多 Agent 避免 57 次无效补证，但与单 Agent 质量持平且本机 P95 更慢；实际模型调用、Token 和 API 费用均为 0；
- 当前开发分支新增 Runtime Invariant Guard：工业 Gate PASS 缺少必需工具/证据检查时失败关闭，具名 CAPA 与只读父证据 Child Run 在跃迁前生成 JCS 回执；这是 executable runtime invariant monitoring，不是 formal verification 或 model checking；
- 当前开发分支的只读 `EvidenceBeliefSnapshot` / Ledger 将支持状态与时效状态拆分；Incident v5 在规划阶段绑定 v2 Ledger，但仍由既有 hypothesis、evidence edge、案件和 evidence bundle SHA 派生，不替代原案件事实源；
- DynamicBench-v2 含 24 优先级 fixtures × 4 输入顺序 × 3 repeats = 288 records；288/288 选择正确、24/24 输入顺序不变、24/24 重复回执稳定，实际模型调用为 0。它只证明冻结字典序选择器语义，不证明已校准 Active Sensing；该选择器只在 Incident v5 的既有白名单和冻结预算内控制 Worker 执行，旧 v1–v4 案件不被改写；
- Agent Core v2 会拒绝不连续事件序号、六阶段首次出现乱序、控制阶段未成功收口及“工具失败但最终 PASS”；Worker 工具失败可形成无 finding 的失败回执并进入人工补证，不会被 Judge 当作成功证据；
- CAPA 派生版本 v2 在目标卷内先构建 staging 树，完成 manifest/receipt 回读校验后以不覆盖目标的目录重命名发布；注入复制失败时最终版本目录不出现，解除故障后可重试。该原子性仅限派生目录命名空间，不是来源授权、数据库、Child Run 与全部回执的跨系统事务；
- `GovernedOutcomeEnvelope v1` 固定绑定父 Gate、Incident/Audit Root、具名决定、CAPA、Child Gate、最终责任队列与 Outcome Assessment 共 12 类已验证工件；本地 JCS 域分离根可发现漂移，但签名、可信时间戳与外部锚仍为 `NOT_CONFIGURED`；
- 冻结公开 release 与 RC3 本地产品回执各自具有交叉 SHA-256 和私有路径扫描；两组数字不得混写。

Omni 源树的 4,464 张图像与 1,439 个 masks 已完成授权声明、只读 profile 与产品任务绑定；Policy Gate 的已验证固定分母仍为 180，不能写成 4,464 张全量认证。操作者授权声明也不等于独立法律权属意见或数据再分发授权。

## 第三层：下一阶段外部验收 `OPEN`

以下事项必须获得对应外部主体、授权环境或平台回执后，才能升级表述：

- 客户/企业 shadow test、客户验收和 ROI；
- 工厂现场只读接入、现场 KPI 和业务责任人确认；
- 生产部署、生产 IAM、SLA/SLO 或自动生产写回；
- 外部 LLM 实际运行与成本回执；
- 真实 LongCat/VGGT/OmniVGGT 服务身份、checkpoint/input hash 绑定、模型效果与外部网络 SLA；
- Omni 4,464 张图像全量 Policy Gate；
- 真实 hosted AgentTeams/Matrix 实例验收；当前静态契约、本地 transport、ProductService/API 接线与假服务集成为 `PASS_LOCAL`，真实连接仍为 `NOT_PROBED`，本地运行时状态保持 `mapped_not_connected`；
- GOAI 复赛 RC3 的官网作品 ID、实际上传文件哈希、上传回执、决赛晋级或获奖；

第三层是扩大采用范围所需的下一批证据，不反向否定第一、二层已经完成的工程实现与固定公开数据实跑。

## 允许使用的强陈述

- “已完成换型后视觉异常处置与方案复验 Agent 的本地可运行闭环；当前过程与视觉方案输入为显式 Fixture 或脱敏离线只读导出。”
- “已实现工作台、REST API、五类工具、证据触发 Dynamic Leader、Frozen Policy Judge、风险处置流、三套候选方案、原子证据底账、同合同 child Run 与证据包；私有权威仓保留完整运行证据，公共镜像仅发布经隐私门禁验证的合成只读回放。”
- “冻结 RC2 已在操作者声明授权的本地离线副本中固定 180 张完成 Policy Gate 实跑：1 次重规划、3 个动态 Worker、45 条 findings、45 张整改工单、8 项规则检查，结论 `RECAPTURE`；公开的是脱敏证据快照，不是原始图像。”
- “RC2 冻结公开快照为 180/45；当前 RC3 `_03` 授权产品运行完成 4,464 张只读 source profile，并对固定 180 张执行 Gate：首次 48、最终 49 条 findings/原子记录，聚合为 3 个风险处置流和 3 套候选方案，5→8 ToolTrace，1 次重规划、3 个动态 Worker，结论 `RECAPTURE`。”
- “RC3 `_05` 已在不改写父来源的私有派生版本执行最高覆盖方案并完成独立 child Run；只关闭 6/49 条责任项，43 条转调查或继续整改，因此不写成恢复成功；`_06` 将最小恢复成本保持为 `NOT_ESTIMABLE`。”
- “已完成 288 条传统流水线、单 Agent、多 Agent 同协议对照；固定 SOP 下多 Agent 必要性未被支持。”
- “DynamicBench-v1 的固定分母结果为 Dynamic Leader P/R 1.0/1.0；它与单 Agent 质量持平且本机 P95 更慢，只证明触发语义与相对固定多 Agent 的无效调用减少。”
- “已在真实本机 loopback socket 上完成 4 项网络韧性固定测试，并在 prompt-injection v2 固定集上完成攻击 12/12 阻断与良性 6/6 放行。”
- “已实现 LongCat/VGGT/OmniVGGT 连接适配器并通过 3/3 本机协议夹具；真实后端连接数为 0，未声明模型效果。”
- “异常案件的实际 Worker 回执、人工中断/恢复、精确 CAPA、派生版本、child Run 和前后哈希相连的阶段事件已在服务层端到端验证；CAPA 数据恢复不会覆盖未关闭的工艺或视觉冲突。”
- “已将完整 Incident→人工决定→CAPA→Child Run→责任队列投影为一个可复算的 `GovernedOutcomeEnvelope`；它是本地 tamper-evident 完整性入口，不是数字签名、可信时间戳、根因证明或生产放行。”

## 需要外部证据后才能使用的表述

- “真实客户已验收”或“已有客户 ROI”；
- “生产级已部署”或“工厂已上线”；
- “外部专家/外部 LLM 已批准”；
- “真实 LongCat/VGGT/OmniVGGT 已连接”或“固定注入规则可防御任意攻击”；
- “全量 Omni 已认证”；
- “真实 Hosted AgentTeams Runtime 已连接、已完成 Worker 执行或已通过生产验收”；
- “真实 OPC UA、VisionMaster SDK、MES/SCADA 或设备控制已接入”；
- “官网已提交、已晋级或已获奖”。
