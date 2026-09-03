# VisionData Gate｜复赛 Q&A 防守卡

## 先说结论的回答

| 评委追问 | 20 秒回答 | 证据入口 | 不能外推 |
|---|---|---|---|
| 这是不是一堆固定规则？ | 工具测量和门禁阈值是确定性的；Agent 的价值在首轮证据出现后选择或拒绝后续 Worker，并把新事实闭环到人工决定和 Child 复验。 | Worker Selection、DynamicBench-v3、Incident v6 | 所有任务都需要多 Agent |
| 为什么不用一个更长的流水线？ | 固定 SOP 中我们保留了多 Agent 不占优的负结论；只有证据冲突、工具故障或不确定性改变任务图时才启用动态补证。 | ArchBench、DynamicBench | 合成优势等于工厂收益 |
| 是否用了真实工业数据？ | 有一条操作者声明授权的私域离线 Pilot，固定 180 张进入 Gate；原始资产不公开，也没有工厂在线 shadow 或客户验收。 | 官方反馈闭环、合规说明 | 客户数据、现场部署、独立权属认证 |
| 为什么误放行率和误拦截率没有数字？ | 当前没有独立双人或 QMS 真值分母。把 0/0 写成 0% 会误导，所以状态保持 `NOT_MEASURED_PENDING_ADJUDICATION`。 | Governance 指标合同 | 用合成 benchmark 替代工厂真值 |
| 49 降到 33 是否说明整改成功？ | 不能。只关闭 6 条责任项，43 条仍开放，Child 仍为 RECAPTURE，所以结果是转人工调查，不是恢复生产。 | Parent/CAPA/Child、Outcome Envelope | 根因成立、生产恢复 |
| Child 显示 PASS 是否能放行？ | 公开 Child 只表示本地合成同合同复验；`production_release_allowed=false` 始终独立，真实生产需要机构 IAM、具名审批和外部回执。 | Lineage、Governance | 生产批准 |
| 大模型会不会编数字？ | 清晰度、dHash、标注偏移等事实由确定性工具产生；模型只能组织假设和计划，Frozen Policy Judge 以工具回执为准。 | Tool Receipt、Policy Judge | 模型判断等于测量事实 |
| 工具失败怎么办？ | 主工具失败时只允许合同内 fallback；无法恢复就 HOLD。DynamicBench-v3 的两条故障夹具恢复 2/2，但这仍是冻结合成测试。 | Runs、DynamicBench-v3 | 所有现场故障已覆盖 |
| 数据和密钥会上传吗？ | 公开 Pages 无后端和密钥入口；本地 BYOK 密钥只在本机服务端保管，原始来源默认只读，公共镜像经过隐私门禁。 | Publication Boundary、Settings、privacy gate | 公网生产 IAM 已完成 |
| 能接 MES、PLC、OPC UA 吗？ | 当前提供显式适配合同和未连接状态；没有真实身份与探测回执前，不能说已经在线接入。 | Integrations、Adapter SDK | 接口存在等于已经连接 |
| 如何复现？ | 仓库提供锁文件、固定合成样本、运行入口、公开清单、测试和 SHA 校验；第三方 clean-clone 回执仍需外部完成。 | README、RUNNING、SBOM、public export | 本地通过等于第三方已复现 |
| 你们属于哪个方向？ | 最新 9 页复赛排期把第 03 队 VisionDataGate 列为 `AI+其他`；项目应用领域仍是工业视觉与制造业数据治理。 | 最新复赛指南第 6 页 | 把历史分类冒充当前排期 |
| 现在是否已经全部提交？ | 冻结 RC3 候选与 RC4 Defense Kit 分别通过各自的本地完整性门；RC4 公共镜像已取得 `PASS_PUBLIC_RC4_SYNC`，但本轮 RC5 文档发布和官网提交仍为 `PENDING`，官方评测仍为 `NOT_EVALUATED`。 | Project Status、Submission Checklist、Actions `33718870200` | RC4 公共部署 PASS 等于 RC5 已发布、官网已提交或官方已验收 |

## 遇到证据缺失时的标准句

> 这部分当前没有外部回执，所以我们保持 `HOLD / NOT_MEASURED / PENDING`。现在能证明的是本地合同、冻结输入和可复现运行；不能证明客户验收、工厂效果或生产授权。
