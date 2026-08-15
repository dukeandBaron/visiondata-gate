# VisionData Gate｜评委五分钟导航

本页把现有工程、证据和边界材料组织成一条最短审阅路径，不新增事实，也不替代机器可读 receipt。

## 1. 先确认赛题与用户价值

VisionData Gate 是 GOAI 赛道二“无界应用 Boundless Agents”中 AI+工业制造方向的应用作品。目标用户是工业视觉算法工程师和数据治理团队；核心任务是判断一个数据批次能否进入实验训练池，并把发现、整改、复验和交付串成闭环。

- 在线评委入口：<https://dukeandbaron.github.io/visiondata-gate/>
- 当前提交 RC2：<https://github.com/dukeandBaron/visiondata-gate/releases/tag/v0.1.0-goai-rc2>
- 冻结实验与证据命名空间：`vdg-20260816-rc1`（RC2 不改实验结论）
- 附件摘要：[`../release/SHA256SUMS.txt`](../release/SHA256SUMS.txt)
- 小白技术路线：[`BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md`](BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md)
- 一页纸：[`one_pager.md`](one_pager.md)

Agent Runtime、Skill、Tool Contract、Policy Judge 和 AgentTeams adapter 是应用的可信后台与复用能力，不改变应用赛道定位。

## 2. 再看为什么不是固定 Workflow

先读 [`ARCHITECTURE_BENCHMARK_AND_DYNAMIC_PLANNING.md`](ARCHITECTURE_BENCHMARK_AND_DYNAMIC_PLANNING.md)：

- ArchBench-v2 固定了输入、工具、合同与 Judge，得到 288 条同协议记录；
- 传统流水线、单 Agent、多 Agent 的错误放行率均为 0%，F1 均为 0.96；
- 因而项目不宣称多 Agent 普遍优越，只把必要边界放在“中间证据改变后续任务”；
- Omni-180-v1 中的 metadata 漂移、分辨率分组和跨工具冲突触发了 1 次 replan 与 3 个动态 Worker。

机器可读入口：

- [`../evidence/submission/vdg-20260816-rc1/architecture_benchmark.json`](../evidence/submission/vdg-20260816-rc1/architecture_benchmark.json)
- [`../evidence/submission/vdg-20260816-rc1/dynamic_leader_plan.json`](../evidence/submission/vdg-20260816-rc1/dynamic_leader_plan.json)
- [`../evidence/submission/vdg-20260816-rc1/omni_gate_receipt.json`](../evidence/submission/vdg-20260816-rc1/omni_gate_receipt.json)

## 3. 抽查完整任务闭环

按以下链路抽查任意一条问题：

```text
工具输出 → finding → work order → rule check → repair/recheck → GateResult
```

实现与协议入口：

- Runtime：[`AGENT_RUNTIME.md`](AGENT_RUNTIME.md)
- 工具/MCP 契约：[`TOOLS_AND_MCP_CONTRACT.md`](TOOLS_AND_MCP_CONTRACT.md)
- 重放与迁移：[`TOOL_REPLAY_AND_MIGRATION.md`](TOOL_REPLAY_AND_MIGRATION.md)
- API：[`API_QUICKSTART.md`](API_QUICKSTART.md)

## 4. 核对声明没有越界

先读 [`CLAIM_SCOPE.md`](CLAIM_SCOPE.md)，再看 [`REVIEWER_READINESS_MATRIX.md`](REVIEWER_READINESS_MATRIX.md)。当前可确认的是本地工程闭环、固定公开数据 pilot、公开评委站点和可复验证据；不能据此升级为客户验收、工厂部署、生产 IAM、外部 LLM 实际调用、全量 Omni Gate 或 hosted AgentTeams 已连接。

AgentTeams 当前状态：静态契约 `PASS`、runtime transport `OPEN`、connection status `mapped_not_connected`。

## 5. 一条命令校验证据

在已经安装锁定依赖的环境中运行：

```powershell
.\.venv\Scripts\python.exe tools\check_release_consistency.py
.\.venv\Scripts\python.exe tools\check_website_data.py
.\.venv\Scripts\python.exe tools\check_release_assets.py --require-all
```

三项检查会核对固定分母、动态任务、GateResult、架构实验、网站投影和五个发布附件的 SHA-256；事实缺失或漂移时退出失败。

## 当前仍需权利主体完成

- 选择并确认顶层 `LICENSE` 与正式 `NOTICE`；
- 通过比赛账号提交，保存官方作品 ID 与平台回执；
- 如需扩大落地声明，补充真实客户、工厂或第三方复验材料。
