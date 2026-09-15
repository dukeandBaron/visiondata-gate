<p align="center">
  <img src="web/public/favicon.svg" alt="VisionData Gate" width="76" />
</p>

<h1 align="center">VisionData Gate</h1>

<p align="center"><strong>把工业视觉异常办到可复验</strong></p>

<p align="center"><strong>GOAI 2026 赛道二「无界应用」· 第 03 队 · 官方排期 AI+其他（工业视觉应用）</strong></p>

VisionData Gate 是面向工业视觉算法工程师与质量负责人的证据驱动异常处置 Agent。确定性工具先测量图像、标注、泄漏、覆盖与治理边界；Agent 只在中间证据改变下一步时动态补证；CAPA、根因和生产决定保留给具名人员，整改后由 Child Run 按同一合同独立复验。

## 现在可以完成什么

| 使用入口 | 当前流程 | 交付结果 |
|---|---|---|
| 还没有任务模型 | 导入并复核图像/标注 → 固定训练准入数据 → 建立候选模型 | 数据版本、问题清单、候选模型及评估记录 |
| 已有模型 | 登记可信运行环境和权重摘要 → 接收新数据或人工反馈 → 生成下一轮候选 | Parent/Child 模型身份、反馈关联、选择或回退记录 |
| 两种入口共用 | 只读测量 → 证据缺口 → Worker 补证 → 人审 → 派生版本复验 | Gate、Finding、工单、审计摘要和未清责任项 |

当前本地工作台包含账户与工作区隔离、图像工作簿、数据池、Agent 任务、模型/API 管理、学习反馈和 CAPA 页面。视觉模型采用外置运行环境和权重；安装包不捆绑 Torch、Ultralytics 或模型文件。

**[打开公开评审首页](https://dukeandbaron.github.io/visiondata-gate-public/)** · **[进入合成工作台](https://dukeandbaron.github.io/visiondata-gate-public/#/command-center)**

<p align="center">
  <img src="docs/assets/web-command-center.png" alt="VisionData Gate 公开合成工作台" width="1180" />
</p>

## 复赛快速入口

本次线上答辩的官方窗口为 8 分钟，其中项目陈述 3 分钟、现场 Demo 1 分钟、问答 3 分钟、评分与切换 1 分钟。当前材料使用 60 秒 Demo 路径；此前 89.9 秒 RC3 视频只作为完整历史备用，不冒充本次现场时限。

- [2026-09-02 最新复赛指南核验](docs/GOAI_SEMIFINAL_GUIDE_20260902.md)
- [60 秒 Demo 脚本](docs/DEMO_60S_SCRIPT_SEMIFINAL.md)
- [3 分钟项目陈述稿](docs/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md)
- [答辩 Q&A 防守卡](docs/DEFENSE_QA_SEMIFINAL.md)
- [答辩运行手册](docs/SEMIFINAL_DEFENSE_RUNBOOK_20260902.md)
- [数据来源与合规说明](docs/DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md)

官方提交与评测状态仍分别为 `PENDING` 和 `NOT_EVALUATED`；公开页面可访问不代表官网提交成功。

## 公开网页能证明什么

GitHub Pages 运行同一套 React 多页面工作台的 `PUBLIC_SYNTHETIC_REPLAY` 模式。它不是截图：浏览器会下载冻结 JSON 清单并复算 JCS SHA-256；只有摘要一致时，页面才展示：

- selected / rejected Workers、选择原因、冻结预算与 triggering evidence；
- 竞争假设、缺失证据和六阶段 Incident v6 状态；
- Parent → Human Gate → Derived → Child 血缘，其中公开清单只证明 `human gate=REQUIRED`；
- `official_submission=PENDING`、`official_evaluation=NOT_EVALUATED` 与 `production_release_allowed=false`。

清单缺失、字段漂移或摘要不一致时，页面显示 `FAIL CLOSED`，不会使用嵌入数字补位，也不会制造 PASS。

公开清单的计数固定为 `3 selected / maximum 5 / 2 rejected / 4 hypotheses / 4 external evidence gaps`，且 `public_snapshot_attestation=NOT_ISSUED`；它只证明静态清单 JCS SHA 自一致，不是后端 provenance、上游不可篡改凭证或具名审批回执。另一条 Goal3 本地持久回执是 `5 selected / budget 5 / 3 rejected / Child CONTINUE_HOLD`；两者不是同一案件或同一来源，数字、ETag、SHA 与结论不得互借。

## 一次完整任务闭环

```text
授权只读来源
→ 确定性 Evidence Gate
→ 竞争假设与证据缺口
→ 动态补证 Worker
→ Frozen Policy Judge
→ 人工闸门 REQUIRED（公开轨不证明具名审批完成）
→ 私有派生整改
→ Child Run 同合同复验
→ 责任队列与 Governed Outcome Envelope
```

AI 可以调查、解释和建议；不能确立根因、批准 CAPA、控制设备或放行生产。

## 量化结果与边界

| 证据轨 | 当前结果 | 禁止外推 |
|---|---|---|
| 授权私域离线 Pilot | findings `49 → 33`；`6 closed / 43 open`；整改后通过率 `0/1`；转人工调查 | 客户验收、工厂部署、生产恢复 |
| DynamicBench-v3 | Dynamic 正确终态 `8/8`，Fixed `4/8`；工具调用 `14 vs 24`；故障恢复 `2/2` | 工厂准确率、客户 ROI |
| 独立复杂冲突配对子集 | Dynamic 误放行 `0/4`，Fixed `4/4` | 与 v3 分母合并 |
| VisA capsules Normality 开发代理 | 三种子 Image AUROC 均值 `0.657823`；正常图像 FPR `0.277778`；Pixel F1 `0.090093` | 工业模型达标、工厂误放行率；三种子不等于三轮动态调优 |
| 工厂级误放行/误拦截 | `NOT_MEASURED_PENDING_ADJUDICATION` | 在没有独立双人/QMS 真值时填写百分比 |

详细分母和协议见 [官方反馈闭环](docs/GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md)、[行业场景价值](docs/INDUSTRY_SCENARIO_VALUE.md) 与 [DynamicBench-v3](docs/DYNAMICBENCH_V3.md)。

v3 的输入、期望终态和两种策略均由作者定义，外部模型调用为 0；ReAct/LangGraph 对照尚未执行，不能把固定流水线当作这些外部 Agent。参数、原始记录与最小复现见 [基准复现及自评偏差](docs/BENCHMARK_REPRODUCIBILITY.md)。

固定 prompt-injection v2 集观察到攻击拦截 `12/12`、良性放行 `6/6`、良性误伤 `0/6`；被阻断攻击的远端模型调用为 0。复现命令为 `uv run visiondata-gate prompt-injection-eval --output output/prompt-injection-review.json`，请使用新的输出文件。上述固定集不证明未知、自适应或多模态攻击的普适防护。

## 公开边界

- 只读静态回放；无 Python 后端、账户、API Key 输入或生产写操作；
- 不包含客户/工厂原图、私域 mask、真实类别名、设备帧、本机数据库、调试日志、API Key、DPAPI 密文、个人提交历史或私有运行回执；
- 公开二进制逐文件绑定 SHA-256，并经过当前树、完整历史与 Pages 构建三道隐私扫描；
- AI 不替代质量负责人、客户机构或主管部门的最终判断；
- 公共镜像使用独立 Git 历史，不包含私有 Release ZIP、PPTX、PDF、视频或完整私有 Git 历史。

完整规则见 [GitHub 与 GitHub Pages 公开边界](docs/PUBLICATION_BOUNDARY.md)。

摘要完整性不等于可信时间或身份签名。若全部本地材料、锚点和验证程序都可被同一方替换，单机 SHA 链不能独立证明旧历史曾存在。参见 [审计信任边界](docs/AUDIT_TRUST_BOUNDARY.md)。

## 本地开发

### Windows 安装候选

[GitHub Releases](https://github.com/dukeandBaron/visiondata-gate/releases) 提供按源码提交和 SHA-256 绑定的 Windows 候选包。下载前先阅读对应 Release 的验证范围；旧标签不会自动包含后续源码修复。

当前源码已修复安装版账户页的三个连接问题：Spring 将桌面 CORS 预检交给 FastAPI 的精确白名单裁决；合法 WebView 写请求同时要求允许来源、正确桌面启动凭证和本机连接；启动配置读取失败后允许用户显式刷新。注册仍采用管理员审批，登录或注册写请求不会自动重放。

安装器仍未签名。每个新安装器必须单独完成资源绑定、原生桌面登录流程和安装/卸载检查，不能继承旧构建的回执。构建与使用边界见 [Windows 安装说明](docs/WINDOWS_INSTALLER.md)。

日常操作使用 **React 工作台**；Tauri 封装同一界面，Streamlit 保留兼容，Reviewer Server 提供证据投影。它们不是四套平行产品。参见 [界面选择](docs/INTERFACE_SUPPORT.md)。

跨平台源码启动（Python 3.12/3.13、uv、Node.js 22.12+）：

```text
uv sync --extra api --extra qa --locked
npm --prefix web ci
uv run python tools/run_cross_platform_workbench.py --check
uv run python tools/run_cross_platform_workbench.py
```

该入口启动本地 API 与 React，不把公开 Pages 变成可写服务；不读取私有 `.env` 或自动调用远端模型。Linux/macOS 实机验收和原生安装包不由源码可运行性推定。CLI、数据目录和会话说明见 [跨平台 Quickstart](docs/CROSS_PLATFORM_QUICKSTART.md)。

Python 内核：

```powershell
uv sync --extra api --extra qa --locked
uv run python -m pytest tests/test_policy_agents.py tests/test_evidence_state.py tests/test_audit_envelope.py
```

React 工作台：

```powershell
cd web
npm ci
npm run typecheck
npm run build
```

公开 Pages 构建：

```powershell
cd web
$env:VITE_VISIONDATA_PUBLIC_REPLAY = "true"
$env:VISIONDATA_WEB_BASE_PATH = "/visiondata-gate-public/"
npm run build
python ..\tools\check_public_pages.py --dist dist
```

本地真实工作台、BYOK Provider、Hosted AgentTeams 和桌面封装具有更强的本机信任边界；请先阅读 [运行说明](docs/RUNNING.md)、[API 快速上手](docs/API_QUICKSTART.md) 与 [外部模型配置](docs/EXTERNAL_MODEL_CONFIGURATION.md)。

## 可复用资产

- `src/visiondata_gate/`：受控 Agent 内核、证据、CAPA、血缘与门禁；
- `schemas/`、`rulepacks/`、`skills/`：可迁移合同与工业规则；
- `adapters/`、`agentteams/`：外部系统的显式适配边界；
- `sample_data/`：固定 seed 合成样本与 SHA-256 清单；
- `web/`：React/Tauri 多页面工作台与静态公开回放；
- `tests/`：合同、失败关闭、安全边界和回放验证。

接口存在不等于外部平台已经连接。CVAT/FiftyOne 已完成本地合同验证；MES、OPC UA、PLC、VisionMaster 和 Hosted AgentTeams 在取得真实身份与探测回执前保持未连接。

第三方 Python 集成应从 [公共 API 与兼容合同](docs/PUBLIC_API.md) 选择入口；文件带版本号不代表旧协议已经弃用。外部建议的核实结果见 [review 逐项响应](docs/EXTERNAL_REVIEW_RESPONSE.md)。

[工程质量门禁](docs/ENGINEERING_QUALITY_IMPLEMENTATION.md) 提供独立工具锁、限定范围类型检查、逐文件行/分支覆盖率和安全扫描。广域类型债务与静态安全告警仍明确保留，不把 scoped PASS 写成全仓或生产安全认证。

当前尚有一项来自 Tauri Linux GTK 依赖链的 `glib 0.18.5` 中等级上游告警；Windows 目标不编译该依赖，Linux 桌面仍保持 HOLD。依赖链与处理边界记录在 [独立质量工具说明](quality/README.md)。

完整 Git 历史隐私扫描也仍为 HOLD：当前可达历史中有 9 个既有提交使用非 noreply 作者邮箱。GitHub/Dependabot Bot 的标准签名格式和 3 个经逐 SHA 复核的历史工作台截图已不再产生误报，但没有把私人邮箱加入白名单，也没有重写远端历史。`tools/export_public_repository.py` 生成的 history-free 快照具有独立门禁；它通过只说明当前导出文件树可公开，不等于完整历史已经通过。

## 状态

```text
github_source=ACTIVE_ENGINEERING_SOURCE
history_free_public_snapshot=REQUIRES_CURRENT_SHA_BOUND_MANIFEST
full_git_history_privacy=HOLD_PENDING_AUTHORIZED_HISTORY_REWRITE
windows_release=UNSIGNED_LOCAL_CANDIDATE
installed_native_gui=REQUIRES_PER_BUILD_RECEIPT
clean_machine_validation=NOT_RUN
industrial_model_effectiveness=HOLD
official_submission=PENDING
official_evaluation=NOT_EVALUATED
factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION
production_release_allowed=false
authority=human_only
```

源码、Pages、安装器和模型运行分别绑定自己的提交或摘要；任何一层成功都不会自动改变比赛、客户、工厂或生产状态。

## License 与供应链

版本内容见 [CHANGELOG](CHANGELOG.md)，引用软件可使用 [CITATION.cff](CITATION.cff)。已有 GitHub prerelease 不代表 PyPI 已发布；发布新包或新安装器前请按 [发布准备](docs/RELEASE_PREPARATION.md) 验证对应源码和产物。

代码采用 [Apache License 2.0](LICENSE)，版权与声明见 [NOTICE](NOTICE)。合并 CycloneDX SBOM 同时绑定 `uv.lock`、`web/package-lock.json` 与 `web/src-tauri/Cargo.lock`；依赖、SPDX 和第三方许可证证据见 [SBOM](docs/SBOM.cdx.json)、[Cargo 许可证快照](docs/CARGO_LICENSES.locked.json)、[第三方依赖清单](docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md) 与 [Notices](docs/THIRD_PARTY_NOTICES.md)。

参与开发前请阅读 [贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md) 与 [社区行为准则](CODE_OF_CONDUCT.md)。请勿在 Issue 或 PR 中上传真实工厂数据、密钥、个人信息或私有运行回执。
