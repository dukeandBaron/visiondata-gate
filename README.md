<p align="center">
  <img src="web/public/favicon.svg" alt="VisionData Gate" width="76" />
</p>

<h1 align="center">VisionData Gate</h1>

<p align="center"><strong>把工业视觉异常办到可复验</strong></p>

<p align="center"><strong>GOAI 2026 赛道二「无界应用」· 第 03 队 · 官方排期 AI+其他（工业视觉应用）</strong></p>

VisionData Gate 是面向工业视觉算法工程师与质量负责人的证据驱动异常处置 Agent。确定性工具先测量图像、标注、泄漏、覆盖与治理边界；Agent 只在中间证据改变下一步时动态补证；CAPA、根因和生产决定保留给具名人员，整改后由 Child Run 按同一合同独立复验。

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
| 操作者声明授权的私域离线 Pilot | findings `49 → 33`；`6 closed / 43 open`；整改后通过率 `0/1`；转人工调查 | 独立权属认证、客户验收、工厂部署、生产恢复 |
| DynamicBench-v3 | Dynamic 正确终态 `8/8`，Fixed `4/8`；工具调用 `14 vs 24`；故障恢复 `2/2` | 工厂准确率、客户 ROI |
| 独立复杂冲突配对子集 | Dynamic 误放行 `0/4`，Fixed `4/4` | 与 v3 分母合并 |
| 工厂级误放行/误拦截 | `NOT_MEASURED_PENDING_ADJUDICATION` | 在没有独立双人/QMS 真值时填写百分比 |

详细分母和协议见 [官方反馈闭环](docs/GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md)、[行业场景价值](docs/INDUSTRY_SCENARIO_VALUE.md) 与 [DynamicBench-v3](docs/DYNAMICBENCH_V3.md)。

## 公开边界

- 只读静态回放；无 Python 后端、账户、API Key 输入或生产写操作；
- 不包含客户/工厂原图、私域 mask、真实类别名、设备帧、本机数据库、调试日志、API Key、DPAPI 密文、个人提交历史或私有运行回执；
- 公开二进制逐文件绑定 SHA-256，并经过当前树、完整历史与 Pages 构建三道隐私扫描；
- AI 不替代质量负责人、客户机构或主管部门的最终判断；
- 私域 Pilot 的来源 URL 与数据再分发许可仍分别为 `OWNER_SOURCE_URL_ACTION_REQUIRED` / `NO_EXPLICIT_REDISTRIBUTION_LICENSE_FOUND`；公共镜像不包含对应原始数据；
- 公共镜像使用独立 Git 历史，不包含私有 Release ZIP、PPTX、PDF、视频或完整私有 Git 历史。

完整规则见 [GitHub 与 GitHub Pages 公开边界](docs/PUBLICATION_BOUNDARY.md)。

## 本地开发

Python 内核：

```powershell
uv sync --frozen
uv run python -m pytest
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

## 状态

```text
current_rc4_defense_kit=PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY
public_mirror_rc4_sync=PENDING
frozen_rc3_candidate=PASS_LOCAL_RC3_RELEASE_CANDIDATE
frozen_rc3_source_commit=c5fd68fc38025ffab4345cd739e611c96b13c530
frozen_rc3_source_tree=5501787b6ed452759af16e60dca76ce0c2ec54bf
official_submission=PENDING
official_evaluation=NOT_EVALUATED
factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION
production_release_allowed=false
authority=human_only
```

冻结 RC3 的 PASS 只绑定上述 commit/tree；当前 RC4 答辩包装未完成全套附件 QA 前保持 HOLD。网页部署成功不会改变比赛、客户、工厂或生产状态。

## License 与供应链

代码采用 [Apache License 2.0](LICENSE)，版权与声明见 [NOTICE](NOTICE)。合并 CycloneDX SBOM 同时绑定 `uv.lock`、`web/package-lock.json` 与 `web/src-tauri/Cargo.lock`；依赖、SPDX 和第三方许可证证据见 [SBOM](docs/SBOM.cdx.json)、[Cargo 许可证快照](docs/CARGO_LICENSES.locked.json)、[第三方依赖清单](docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md) 与 [Notices](docs/THIRD_PARTY_NOTICES.md)。

参与开发前请阅读 [贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md) 与 [社区行为准则](CODE_OF_CONDUCT.md)。请勿在 Issue 或 PR 中上传真实工厂数据、密钥、个人信息或私有运行回执。
