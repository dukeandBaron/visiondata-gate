# VisionData Gate｜评委五分钟导航

本页把现有工程、证据和边界材料组织成一条最短审阅路径，不新增事实，也不替代机器可读 receipt。

## 1. 先确认赛题与用户价值

VisionData Gate 是 GOAI 赛道二“无界应用 Boundless Agents”中 AI+工业制造方向的应用作品。目标用户是工业视觉算法工程师、质量负责人和数据治理团队；核心任务是把换型后的图像、标注、metadata、工单、工艺与视觉方案组织成版本化异常案件，并把证据资格化、动态调查、人工决定、私有派生整改、Child Run 复验和交付串成闭环。

- 评委网站与仓库：采用“私有权威仓 + 隐私安全公共镜像”双仓边界；公共镜像只提供 `PUBLIC_SYNTHETIC_REPLAY`，是否为当前版本以 `PUBLIC_MIRROR_MANIFEST.json`、GitHub Actions 与 Pages 部署 SHA 为准
- 官方手册规则锚点：[`GOAI_BOUNDLESS_AGENTS_HANDBOOK_20260825.md`](GOAI_BOUNDLESS_AGENTS_HANDBOOK_20260825.md)
- 初赛历史 RC2 标识：`v0.1.0-goai-rc2`（历史标签不代表当前 RC3 公共镜像或参赛包）
- 复赛 RC3：`PASS_LOCAL_RC3_RELEASE_CANDIDATE / OFFICIAL_PENDING`
- 冻结实验与证据命名空间：`vdg-20260816-rc1`（RC2 不改实验结论）
- 附件摘要：[`../release/SHA256SUMS.txt`](../release/SHA256SUMS.txt)
- 小白技术路线：[`BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md`](BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md)
- 一页纸：[`one_pager.md`](one_pager.md)

项目采用双层结构：工业视觉异常处置 Agent 是用户可见的应用主线；Agent Runtime、Skill、Tool Contract、Policy Judge、可重放证据和 AgentTeams adapter 是可复用的 Infra 加分层。后者直接增强 Agent 闭环、技术深度、安全追溯和开放复用，同时保持应用赛道定位清晰。

## 2. 再看为什么不是固定 Workflow

先读 [`ARCHITECTURE_BENCHMARK_AND_DYNAMIC_PLANNING.md`](ARCHITECTURE_BENCHMARK_AND_DYNAMIC_PLANNING.md)：

- ArchBench-v2 固定了输入、工具、合同与 Judge，得到 288 条同协议记录；
- 传统流水线、单 Agent、多 Agent 的错误放行率均为 0%，F1 均为 0.96；
- 因而项目不宣称多 Agent 普遍优越，只把必要边界放在“中间证据改变后续任务”；
- Omni-180-v1 中的 metadata 漂移、分辨率分组和跨工具冲突触发了 1 次 replan 与 3 个动态 Worker。
- 当前 RC3 `_03` 将用户授权的本地源接入产品对象链：4,464 张只读 profile、固定 180 Gate、48→49 findings/原子记录、5→8 ToolTrace、1 replan、3 Workers；49 条底账聚合为 3 个风险处置流和 3 套候选方案，独立验证 27/27 `PASS`；与 RC2 的 45 条历史数字分开保存。
- DynamicBench-v1 另用 12 个动态正例、12 个负例与四架构同协议网格固定触发分母：Dynamic Leader P/R 为 1.0/1.0，但与单 Agent 质量持平且本机 P95 更慢；固定多 Agent 多做 57 次无效补证。
- `_05` 已在私有派生版本执行最高覆盖方案并创建独立 child Run：49→33 findings，但只证实关闭 6 条责任项、43 条仍打开，终态为 `TRANSFERRED_TO_INVESTIGATION`；`_06` 因此将当前授权候选池的最小恢复成本标为 `NOT_ESTIMABLE`。

机器可读入口：

- [`../evidence/submission/vdg-20260816-rc1/architecture_benchmark.json`](../evidence/submission/vdg-20260816-rc1/architecture_benchmark.json)
- [`../evidence/submission/vdg-20260816-rc1/dynamic_leader_plan.json`](../evidence/submission/vdg-20260816-rc1/dynamic_leader_plan.json)
- [`../evidence/submission/vdg-20260816-rc1/omni_gate_receipt.json`](../evidence/submission/vdg-20260816-rc1/omni_gate_receipt.json)

## 3. 抽查完整任务闭环

按以下链路抽查任意一条问题：

```text
工具输出 → finding → 原子记录 → 风险处置流 → 候选方案 → 人工批准
→ 私有派生版本 → child Run 同合同复验 → 关闭 / 退回 / 转调查 → GateResult
```

实现与协议入口：

- Runtime：[`AGENT_RUNTIME.md`](AGENT_RUNTIME.md)
- 工具/MCP 契约：[`TOOLS_AND_MCP_CONTRACT.md`](TOOLS_AND_MCP_CONTRACT.md)
- 重放与迁移：[`TOOL_REPLAY_AND_MIGRATION.md`](TOOL_REPLAY_AND_MIGRATION.md)
- Agent 评测工具与故障干预：[`AGENT_EVALUATION_TOOLS_20260823.md`](AGENT_EVALUATION_TOOLS_20260823.md)
- 运行时网络、注入与后端合同总 QA：[`../10_reports/RUNTIME_HARDENING_QA_20260824.md`](../10_reports/RUNTIME_HARDENING_QA_20260824.md)
- API：[`API_QUICKSTART.md`](API_QUICKSTART.md)

## 4. 核对声明没有越界

先读 [`CLAIM_SCOPE.md`](CLAIM_SCOPE.md)、[`DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md`](DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md)，再看 [`REVIEWER_READINESS_MATRIX.md`](REVIEWER_READINESS_MATRIX.md)。当前可确认的是本地工程闭环、授权 Omni 数据源产品运行、固定 180 Gate、真实私有派生版本与 child Run、运行时加固固定集、本机后端协议夹具，以及隐私安全的公开合成回放；公开镜像不连接私域后端，不能据此升级为客户验收、工厂部署、生产 IAM、真实外部模型已连接、4,464 全量 Omni Gate 或 hosted AgentTeams 已连接。

AgentTeams 当前状态：静态契约 `PASS`、runtime transport `OPEN`、connection status `mapped_not_connected`。

## 5. 一条命令校验证据

在已经安装锁定依赖的环境中运行：

```powershell
.\.venv\Scripts\python.exe tools\check_release_consistency.py
.\.venv\Scripts\python.exe tools\check_website_data.py
.\.venv\Scripts\python.exe tools\check_release_assets.py --require-all
```

以上三项只校验冻结 RC2。当前 RC3 使用 `build_rc3_release_evidence.py` 生成 detached release namespace，并用 `verify_release_attestation.py` 对该 namespace、匹配的 clean checkout 与声明 toolchain 做本地完整性验证；只有 verifier 返回 `PASS_LOCAL_INTEGRITY` 才成立本地候选状态。RC2 工具不得用 `--force` 覆盖历史附件。

## 当前仍需权利主体完成

- 补全 Omni 原下载页面 URL/平台记录；在无明确再分发许可证时继续排除全部原始数据；
- 对最终候选执行独立 post-build fresh-extract API/Web 与浏览器 smoke；该回执不冒充 Attestation 绑定项；
- 通过比赛账号提交复赛材料，保存官方作品 ID、实际上传文件哈希与平台回执；
- 如需扩大落地声明，补充客户 shadow test、工厂在线系统/现场验收、真实 LongCat/VGGT/OmniVGGT 或第三方复验材料。
