<p align="center">
  <img src="web/public/favicon.svg" alt="VisionData Gate" width="82" />
</p>

<h1 align="center">VisionData Gate</h1>

<p align="center"><strong>让工业视觉异常从发现走到可复验决策</strong></p>
<p align="center"><em>Evidence-first governance for industrial vision data, with human authority and reproducible outcomes.</em></p>

<p align="center">
  <a href="https://github.com/dukeandBaron/visiondata-gate-public/actions/workflows/ci.yml"><img src="https://github.com/dukeandBaron/visiondata-gate-public/actions/workflows/ci.yml/badge.svg" alt="Public source verification" /></a>
  <a href="https://github.com/dukeandBaron/visiondata-gate-public/actions/workflows/pages.yml"><img src="https://github.com/dukeandBaron/visiondata-gate-public/actions/workflows/pages.yml/badge.svg" alt="Public workbench build" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2563eb.svg" alt="Apache-2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12--3.13-3776ab.svg" alt="Python 3.12 to 3.13" />
  <img src="https://img.shields.io/badge/React-19-61dafb.svg" alt="React 19" />
  <img src="https://img.shields.io/badge/Tauri-2-f59e0b.svg" alt="Tauri 2" />
  <img src="https://img.shields.io/badge/authority-human--only-d97706.svg" alt="Human-only authority" />
</p>

<p align="center">
  <a href="https://dukeandbaron.github.io/visiondata-gate-public/"><strong>在线体验</strong></a> ·
  <a href="https://dukeandbaron.github.io/visiondata-gate-public/#/command-center"><strong>打开工作台</strong></a> ·
  <a href="docs/RUNNING.md"><strong>本地运行</strong></a> ·
  <a href="docs/API_QUICKSTART.md"><strong>API</strong></a> ·
  <a href="https://github.com/dukeandBaron/visiondata-gate-public/releases"><strong>发布版本</strong></a>
</p>

<p align="center">
  <img src="docs/assets/web-command-center.png" alt="VisionData Gate 工业视觉数据治理工作台" width="1180" />
</p>

<p align="center"><sub>公开站点为隐私安全的合成回放；本地部署将同一工作台连接到受控 Python API。</sub></p>

## 这是什么

VisionData Gate 是一个本地优先的工业视觉数据治理与发布工作台。它把图像、标注、metadata、批次上下文与整改工作组织成版本化案件：

- 确定性工具测量可观察事实；
- 只有当证据缺口会改变下一步动作时，Agent 才选择额外 Worker；
- Frozen Policy Judge 在证据缺失、冲突或无效时失败关闭；
- CAPA、根因和生产决定始终由具名人员负责；
- Child Run 按同一合同复验私有派生版本。

这是数据治理与发布控制系统，不是缺陷检测模型、自动 PLC 控制器，也不替代质量负责人。

> **私有数据验证边界**
>
> 产品链已在操作者声明授权的私有离线数据副本上运行，证明软件可以在只读来源合同下处理真实数据字节；它**不证明**客户验收、在线工厂 shadow、生产误放行/误拦截率或 ROI。

## 为什么需要 VisionData Gate

工业视觉风险很少只是单一的“模型准确率”问题：

1. **证据分散**：图像、标注、采集 metadata、工单和策略版本散落在不同工具中；
2. **多个解释并存**：采集漂移、跨划分泄漏、标注几何、覆盖缺口与工艺变化可能同时成立；
3. **整改与复验断链**：finding 变少不会自动证明根因、关闭责任或授权生产。

VisionData Gate 把这些事实收进同一个案件，并让每一次状态转换都可检查、可追溯。

## 治理闭环如何运行

~~~text
授权只读来源
        |
        v
Typed Intake + Evidence Gate
        |
        v
竞争假设 + 缺失证据
        |
        v
Selected / Rejected Workers + 原因 + 预算 + 回执
        |
        v
Frozen Policy Judge: PASS | RECAPTURE | HOLD | DEFER
        |
        v
具名人工决定
        |
        v
私有派生整改
        |
        v
Child Run 同合同复验
        |
        v
责任队列 + Decision Packet + Audit Envelope
~~~

## 核心能力

| 能力 | 仓库中的真实实现 |
|---|---|
| 确定性证据工具 | 只读检查图像质量、重复/跨划分泄漏、标注几何、覆盖与 metadata 合同 |
| 证据缺口规划 | 记录 selected/rejected Worker、原因、triggering evidence 与有界预算 |
| 故障感知执行 | 可重试与不可重试故障遵循不同合同；未解决证据保持阻断 |
| 人工治理 CAPA | 批准绑定具名人员与版本；整改只写入私有派生副本，不覆盖 Parent |
| 独立复验 | 即使 Child 仍失败，Parent → Human Gate → Derived → Child 血缘依然可见 |
| 可核验交付 | ToolTrace、GateResult、DecisionPacket 与 GovernedOutcomeEnvelope 通过 JCS/SHA-256 和响应 ETag 绑定 |
| 本地集成 | FastAPI、SQLite、React/Tauri、BYOK Provider、Site/Rule Pack 与窄接口 Adapter |

这里的 SHA-256 用于内容身份与篡改感知；它不是数字签名、可信时间戳，也不能证明谁批准了某个动作。

## 产品工作台

React 应用是多页面操作工作台，不是单一脚本化仪表盘。

| 页面 | 操作者任务 |
|---|---|
| 图像工作簿 | 导入授权图像、检查像素/梯度、修订 BBox 并创建 Agent 任务 |
| 工作总览 | 跟踪计划阶段、Worker 选择、证据缺口、预算与工具故障 |
| 案件与审核 | 检查 Parent Case、竞争假设、缺失证据和下一安全动作 |
| CAPA | 准备、批准或拒绝受控整改，并启动 Child Run |
| 证据与运行 | 查看或下载强类型工件、回执与复验状态 |
| 血缘 | 回放 Parent → Human → Derived → Child |
| 治理 | 分离私域离线验证与工厂 shadow 指标；缺失真值保持未测量 |
| 集成与设置 | 配置本地数据源与 BYOK Provider，密钥不暴露给浏览器或公开站点 |

GitHub Pages 固定为 <code>PUBLIC_SYNTHETIC_REPLAY</code>：没有私域 API、账户、密钥输入或机台写入路径；冻结清单缺失或摘要漂移时会失败关闭。

## 验证证据：分母严格分离

| 证据轨 | 已观察结果 | 只支持什么结论 |
|---|---|---|
| 授权私域离线 Pilot（历史） | Source Profile：4,464 images / 1,439 masks；固定 Gate：180；Parent → Child findings：49 → 33；责任项：6 closed / 43 open；整改通过：0/1 | 产品闭环能处理授权数据字节并保留失败复验；不是客户验收或工厂效果 |
| VisA 公开工业代理 RC5 正式复验 | 300 clean + 300 programmatic block = 600 episodes；Dynamic / Fixed 正确终态均 525/600；unsafe release 均为 0；瞬时恢复均 150/150；调用 2,550 vs 2,700；不可恢复冗余重试 0 vs 150 | 程序化治理真值下的合同感知效率；不证明 Worker replanning、自然缺陷精度、工厂指标或 ROI |
| DynamicBench-v3 合成编排 | 正确终态 8/8 Dynamic vs 4/8 Fixed；调用 14 vs 24；可恢复工具故障 2/2 vs 0/2 | 冻结冲突、故障、不确定性与正常夹具下的动态编排差异；不是工业 KPI |

VisA 正式运行已于 2026-09-03 在 RC5 当前环境复验为 `PASS`。report semantic SHA-256：`1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c`；implementation receipt semantic SHA-256：`7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf`。Dynamic 与 Fixed 终态质量相同，因此不主张 Dynamic 更准确；可支持的差异是 Dynamic 避免了 150 次不可恢复故障冗余重试。

工厂误放行率、误拦截率与独立裁决的整改通过率仍保持 `NOT_MEASURED_PENDING_ADJUDICATION`，直到预注册 shadow 窗口提供 QMS 或双人复核真值；对应 numerator、denominator、value 与置信区间均为 null。Synthetic、公开代理和私域 Pilot 的分母不会合并。完整协议与限制见 [Evidence & Benchmarks](docs/EVIDENCE_AND_BENCHMARKS.md)、[行业场景价值](docs/INDUSTRY_SCENARIO_VALUE.md) 与 [DynamicBench-v3](docs/DYNAMICBENCH_V3.md)。

## 快速开始

### Windows 工作台

环境要求：Python 3.12 或 3.13、Node.js 22+、[uv](https://docs.astral.sh/uv/)。

~~~powershell
git clone https://github.com/dukeandBaron/visiondata-gate-public.git
cd visiondata-gate-public

.\setup_env.ps1
.\run_workbench.ps1 -Install
~~~

启动器会创建本地会话能力，在 <code>127.0.0.1:8787</code> 启动 FastAPI，构建 React 工作台，并打开 <code>127.0.0.1:4173/workspace</code>。

### 分别启动后端与 Web

~~~powershell
# 终端 1：按 docs/RUNNING.md 配置本地会话
.\run_api.ps1

# 终端 2
.\run_web.ps1 -Install
~~~

### 验证

~~~powershell
uv run python tools/run_public_test_suite.py

cd web
npm ci
npm run check
~~~

会话、product root 和公开回放参数见 [运行说明](docs/RUNNING.md)。启用 BYOK Provider 前请先阅读 [外部模型配置](docs/EXTERNAL_MODEL_CONFIGURATION.md)。

## 架构与扩展点

~~~text
web/                       React 19 + TypeScript 工作台、Tauri 2 外壳
src/visiondata_gate/       Incident 内核、工具、CAPA、血缘与交付
schemas/                   可移植 Evidence 与 Adapter 合同
rulepacks/                 声明式策略扩展
skills/                    受控工业 Skill 合同
adapters/                  只读集成示例
agentteams/                Hosted / Local Transport 合同
sample_data/               隐私安全的确定性夹具
tests/                     合同、故障、安全与回放验证
tools/                     构建、基准、隐私与发布门
docs/                      架构、API、证据与运行文档
~~~

接口存在不等于部署已经完成。CVAT/FiftyOne 已有本地合同覆盖；MES、OPC UA、PLC、VisionMaster 与 Hosted AgentTeams 在取得真实身份、端点和探测回执前保持未连接。

## 源码与公开边界

公共镜像由显式 allowlist 从干净私有提交中导出。

| 公开包含 | 明确排除 |
|---|---|
| <code>src/</code>、<code>web/</code>、<code>desktop/</code>、<code>reviewer_workbench/</code>、<code>tools/</code>、<code>tests/</code>、<code>schemas/</code>、<code>skills/</code>、<code>rulepacks/</code>、<code>adapters/</code>、<code>agentteams/</code> 与 <code>examples/</code> 下全部 Git 已跟踪源码 | 私有图像/mask、客户或操作者回执、本地数据库、API Key、DPAPI 密文、日志、构建缓存、release 归档和私有 Git 历史 |
| 锁文件、示例、sample data、许可证清单与 CycloneDX SBOM | 再分发权未确认的来源 URL 或标签 |

<code>PUBLIC_MIRROR_MANIFEST.json</code> 为每个导出文件登记 SHA-256；导出器与隐私扫描器本身也包含在仓库中。文件总数不在 README 中硬编码。

## 安全与责任边界

- 来源数据默认只读；整改只写入私有派生版本；
- 私域原始图像不进入公共镜像或参赛附件；
- Provider 密钥留在服务端，公开 Pages 不渲染密钥；
- <code>machine_write_permitted=false</code>，生产决定权保持 <code>human_only</code>；
- 缺失证据、无效合同、预算耗尽和无法核验的响应全部失败关闭；
- 不要在 Issue 或 Pull Request 中提交工厂数据、密钥、个人信息或私域运行回执。

使用非公开数据前，请阅读 [Security](SECURITY.md)、[公开边界](docs/PUBLICATION_BOUNDARY.md) 与 [数据来源和合规](docs/DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md)。

## 文档

| 快速入口 | 深入阅读 |
|---|---|
| [产品总览](docs/00_OVERVIEW.md) | [Agent Runtime](docs/AGENT_RUNTIME.md) |
| [运行说明](docs/RUNNING.md) | [Incident Control Plane](docs/INCIDENT_CONTROL_PLANE.md) |
| [API Quickstart](docs/API_QUICKSTART.md) | [Governed Outcome Envelope](docs/GOVERNED_OUTCOME_ENVELOPE.md) |
| [外部模型配置](docs/EXTERNAL_MODEL_CONFIGURATION.md) | [开放复用合同](docs/OPEN_REUSE_CONTRACTS.md) |
| [Evidence & Benchmarks](docs/EVIDENCE_AND_BENCHMARKS.md) | [声明边界](docs/CLAIM_SCOPE.md) |

<details>
<summary><strong>GOAI 2026 复赛证据与答辩附录</strong></summary>

比赛材料放在折叠附录中，让仓库首页首先服务产品用户与开发者。当前复赛指南强调行业价值、可演示的应用闭环、可核验工程材料以及数据/合规边界。

- [GOAI 评分证据索引](docs/GOAI_SCORE_EVIDENCE_INDEX.md)
- [最新复赛指南核验](docs/GOAI_SEMIFINAL_GUIDE_20260902.md)
- [3 分钟陈述稿](docs/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md)
- [60 秒 Demo 路径](docs/DEMO_60S_SCRIPT_SEMIFINAL.md)
- [答辩 Q&A](docs/DEFENSE_QA_SEMIFINAL.md)
- [评审就绪矩阵](docs/REVIEWER_READINESS_MATRIX.md)

公共部署、官网提交、官方评测、客户验收与生产放行是相互独立的状态。当前证据绑定标签见 [项目状态](docs/PROJECT_STATUS.md)。

</details>

## 参与贡献

欢迎提交 Issue 与边界清晰的 Pull Request。开始前请阅读 [贡献指南](CONTRIBUTING.md)、[支持说明](SUPPORT.md)、[安全说明](SECURITY.md)、[行为准则](CODE_OF_CONDUCT.md) 与 [变更记录](CHANGELOG.md)。研究复用时可通过 [CITATION.cff](CITATION.cff) 绑定所用版本或提交。

## License 与供应链

VisionData Gate 采用 [Apache License 2.0](LICENSE)，版权说明见 [NOTICE](NOTICE)。依赖来源通过 [CycloneDX SBOM](docs/SBOM.cdx.json)、[生成式许可证清单](docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md) 与 [第三方声明](docs/THIRD_PARTY_NOTICES.md) 发布。
