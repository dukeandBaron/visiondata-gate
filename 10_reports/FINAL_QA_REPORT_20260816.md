# VisionData Gate｜GOAI 初赛终版 QA 报告

报告对象：提交包 `v0.1.0-goai-rc2`，冻结证据 `vdg-20260816-rc1`。本文件名对应初赛截止版本；所有时间均使用 Asia/Shanghai。

## 当前结论

状态：`LOCAL_RC_READY_ACCOUNT_ACTIONS_PENDING`。

VisionData Gate 的参赛主叙事为 GOAI 赛道二“无界应用 Boundless Agents”中的 AI+工业制造应用：工业视觉数据治理与发布 Agent。Agent Infra 仅作为动态补证、工具失败关闭、证据追踪、API 接入和组件复用的可信后台。

核心应用、公开证据 release、在线评委网站、Reviewer Mode、PPT 与 PDF 已存在。2026-08-15 23:48（Asia/Shanghai）完成 RC2 本地工程门禁：pytest 为 `166 passed / 1 skipped / 1 warning / 0 failed`；Ruff rules、Ruff format、compileall 与 `uv lock --check` 均通过。新增回归测试覆盖 Windows `cp1252` 输出和 CI 原生命令失败传播。跳过项是当前 Windows 环境不可创建文件 symlink；警告来自 Starlette TestClient 的依赖弃用提示，不是业务测试失败。GitHub Windows/Linux CI 结果以 RC2 tag 对应工作流为最终跨平台凭证。

在线评委网站已通过 Playwright Chromium 在 1440×1000 与 390×844 两个视口验收：横向溢出均为 0，page/console error 与失败资源请求均为 0；Canvas 具备有效像素尺寸，点击 metadata 动态 Worker 后证据面板正确更新，移动导航与 8 项规则列表可用。终版 PPT/PDF 已完成 12 页逐页目检：模板 fidelity `PASS / 0 issues`、PPT 无画布溢出、12/12 页均含 `[Sources]` notes、无空结构占位符；PDF 为 12 页、960×540 pt，全页渲染无裁切、重叠、乱码或黑块。

候选 ZIP 使用固定 allowlist、固定元数据和 manifest 哈希执行凭据、陈旧声明、私有路径及干净解压审计；最终文件的条目数、SHA-256、字节数、双构建一致性和 exact-package cleanroom 结果以包外 detached receipt 为准，避免包内自引用。因此本文件不得被解释为官网提交回执。

## 固定证据边界

- `Synthetic-v3`：12 个注入真值问题；属于合成工程闭环证据。
- `ArchBench-v2`：288 条同协议记录；固定 SOP 下不支持多 Agent 必要性，不宣称多 Agent 普遍更优。
- `Omni-180-v1`：固定 180 张公开图像完成 Gate；1 次 replan、3 个动态 Worker、45 条 finding、45 张工单、8 项规则检查，结论为 `RECAPTURE`。
- Omni 源树 4,464 张图像和 1,439 个 masks 仅完成结构/解码审计，不属于全量 Gate 认证。
- 本版本实际模型调用数为 0；本地确定性 Worker 不描述为外部 LLM 或真人专家。
- AgentTeams v1.2.2 静态契约为 `PASS`，runtime transport 为 `OPEN`，连接状态为 `mapped_not_connected`。

## 候选包核验边界

- 包内报告只记录预构包契约审计与无自引用状态；最终 ZIP 的精确哈希和 exact-package cleanroom 结果见同名包外 `.receipt.json`。
- 任何重新编辑源码、PPT、PDF、报告或证据文件的操作都会使 detached receipt 失效，必须重新构包和验包。

## 不在本地工程可证明范围内

当前不声称客户验收、真实工厂现场验证、生产部署或 IAM、外部 LLM 执行、完整 Omni 数据集 Gate、hosted AgentTeams/Matrix 连接、官网提交、作品 ID 或获奖。代码已由权利主体确认按 Apache-2.0 开源；顶层 LICENSE、NOTICE、第三方声明与 `REVIEW_REQUIRED=0` 的 SBOM 清单进入 RC2 构包硬门禁。该代码许可不代表外部数据、模型或客户资产已授权。
