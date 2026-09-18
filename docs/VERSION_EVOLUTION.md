# VisionData Gate 版本演进与身份规则

本页回答两个问题：项目每一阶段实际增加了什么，以及某个源码、安装包或实验
回执到底属于哪一版。它不是新的发布证明；当前事实仍以 Git tag、commit、
构建清单、验证回执和摘要为准。

## 先区分四类版本

```text
竞赛里程碑 ≠ Python 包版本 ≠ Windows 构建身份 ≠ Git 提交
```

| 身份 | 示例 | 作用 | 不能代表 |
| --- | --- | --- | --- |
| 竞赛／工程里程碑 | `RC2`、`v0.3.0-goai-rc3`、`v0.4.0-goai-semifinal-rc4` | 冻结一组阶段性叙事、材料和证据范围 | PyPI 包已发布、当前 main 已包含、生产已批准 |
| Python 包元数据 | `pyproject.toml` 中的 `0.1.0` | 标识当前 Python 工程包接口版本 | 某个 Windows 构建、RC4 或 GitHub Release 的全部内容 |
| Windows 构建身份 | tag、源 commit、`BUILD_MANIFEST.json`、安装器 SHA-256 | 标识一次具体打包及其验证对象 | 后续源码修复自动进入旧安装包 |
| Git 提交 | 完整 commit SHA | 精确定位源码树 | 安装、GUI、模型效果或官方提交已经成功 |
| 证据身份 | namespace、JCS 摘要、Case Audit Root、验证 receipt | 固定某次输入、合同、运行与结论 | 法律签名、可信时间戳或不可重写的外部历史 |

因此，旧版本回执不会自动证明当前源码或新安装包。任何新候选必须重新绑定源
commit、构建产物、验证分母和对应摘要。

## 阶段演进

| 阶段与可核验标识 | 该阶段真正完成的变化 | 延续到当前的价值 | 明确边界 |
| --- | --- | --- | --- |
| RC1 内部证据命名空间 `vdg-20260816-rc1` | 冻结 Synthetic-v3、ArchBench-v2、动态调度计划和基础证据工件，建立可复验实验入口 | 奠定“先测量、再裁决、按证据决定是否补证”的基线 | 是内部证据 namespace，不等于 GitHub Release 或生产版本 |
| RC2 历史标识 `v0.1.0-goai-rc2` | Omni-180 冻结脱敏基线记录 180 个样本、45 条 finding／工单、1 次 replan、3 个动态 Worker，裁决为 `RECAPTURE` | 证明动态补证路径可以落到结构化回执 | 这是文档中的历史初赛标识；不得仅凭名称推定当前远端存在同名 tag，也不替代 RC3 |
| RC3 prerelease `v0.3.0-goai-rc3` | 将 Incident v6、竞争假设、Worker 选择、风险处置、具名人工闸门、派生整改和 Child Run 串成闭环；授权私域运行记录 `48 → 49` finding、`5 → 8` ToolTrace，以及复验 `49 → 33` | 形成 Parent／Human／Derived／Child 与 fail-closed 负向闭环 | 只证实 6 条责任项关闭、43 条仍打开，终态转调查；公开 prerelease 只含隐私安全镜像，不含私域原图和回执 |
| RC4 prerelease `v0.4.0-goai-semifinal-rc4` | 面向复赛整理 60 秒 Demo、防守材料、静态 `PUBLIC_SYNTHETIC_REPLAY` 和边界说明 | 让评委可在不接触私域数据的情况下查看冻结合成证据 | Release notes 仍为 `official_submission=PENDING`、`official_evaluation=NOT_EVALUATED`、`production_release_allowed=false` |
| Windows 候选 `windows-local-ce72604-20260914` | 将 React／Tauri／Spring／FastAPI 本地链打包；最终 NSIS 工件记录资源、HTTP 与两轮学习流程验证 | 证明可形成自包含 Windows 候选，而不是只有源码 | 未签名；该候选没有安装后原生 GUI、独立干净机或同版本升级验证 |
| Windows 登录修复候选 `windows-local-dc3a4b-login-fix-20260915` | 修复 WebView CORS、桌面启动凭证与启动配置刷新；回执记录真实 Tauri WebView → IPC → Spring → FastAPI 的账户流程和 NSIS 安装／启动／卸载 | 解决“安装包登录注册卡住”的具体问题 | 仍未签名；独立干净机未运行；Torch、Ultralytics、权重和工业模型效果仍在包外／HOLD |
| Windows 候选 `windows-local-ca1fa7b-20260915` | 将评审术语、YOLO 10–600 秒合同、同 split 字节/像素重复阻断、磁盘/retention、安装器旁附清单和发布版 UIA 验收工具冻结为 350 文件源码并重新打包 | 安装器完成 PYZ 源码匹配、120 次网关请求、两轮包内学习、真实安装启动和七步登录注册 GUI 验收 | 仍未签名；独立干净机和同版本覆盖升级未运行；工业模型效果、客户验收和生产放行保持 HOLD；详见 [候选记录](WINDOWS_CANDIDATE_CA1FA7B_20260915.md) |
| 源码回归锚点 `9417f012…` | 合并唯一主仓链接、异常 Operating Point 源码组件、AgentTeams 路径控制字符防护、学习慢测隔离和公开/私有测试边界；连续回归 2066 passed、27 skipped、0 failed | 当前主仓候选可以展示更完整且可复算的源码与诚实验证分母 | 尚未重新生成 Windows 安装包；skip 能力、GitHub CI、Pages 新部署、工厂 KPI、客户验收和官方结果不由本地源码回归替代 |
| Windows 决赛评审候选 `windows-local-f7f31f7-finals-20260916` | 将决赛五维事实源、技术路线、异常 Operating Point 组件、历史档案测试边界和最终锁定依赖冻结为355文件并重新构建 | 绑定同一公开提交，完成26个PYZ模块匹配、113/113提取态检查、两轮包内学习、NSIS实装、七步UIA、卸载和2070 passed全仓回归 | 仍未签名；独立干净机和同版本升级未运行；工业效果、客户验收、hosted业务后端和生产放行保持HOLD；详见 [候选记录](WINDOWS_CANDIDATE_F7F31F7_20260916.md) |
| `CURRENT_SOURCE_DOCUMENTATION` | 在已验证 Windows 运行时代码之后更新候选记录、README、公开清单和下载链接 | GitHub 首页可以指向已验候选及真实边界 | 文档/清单提交不会自动进入 `f7f31f7` 二进制，也不产生 PyPI、工厂 KPI、客户验收或官方评测结果 |

## 当前架构变化如何理解

### 2026-09-19：Normality 单次适应与反馈执行链

本轮源码新增实际 PNG 读取与验封、具名反馈持久化、模型重新批准、受控 CPU
单次 TTT，以及反馈导入工作簿、人工框选后生成 OPEN 工单的两阶段桥接。
TTT 冻结父包、主干与阈值，仅更新当前会话 student，独立参考组不合格或退化
则拒绝/回滚。真实模型包完成 3 步更新，16 张开发参考的 FP/FN 前后均为 2/3；
这是运行证据，不是模型精度提升或工厂验收。

同步补齐独立 worker 资源和 API/Schema 的安装构建检查，以及 Windows
隔离运行环境导入 Torchvision 的匿名用户兼容修复。历史 pack 的策略源码
兼容只允许已经证明是文档文字差异的精确摘要对；任何函数体变化不能借此
继承旧训练证据。[执行合同与实跑摘要](NORMALITY_TTT.md)

旧安装器与旧 main 不自动包含这次新增能力。新二进制必须按新源码清单单独
构建与验收；PR、源码、安装运行、原生 GUI、干净机与工厂效果仍分别记录。

最新源码将业务说明收敛为三段：

1. `HUMAN_AI_COLLABORATIVE_DATASET_BOOTSTRAP`：人机协同数据集冷启动；
2. `AGENT_ORCHESTRATED_DATA_QUALITY_GOVERNANCE`：Agent 编排的数据质量治理；
3. `GOVERNED_MODEL_DEVELOPMENT_AND_FEEDBACK`：受控模型开发与反馈回流。

治理阶段的 Detector／Solver／Evaluator／Planner 草图不被宣传为四个新 Agent，
而是映射为五个有权限边界的受控功能。Solver 被拆成整改规划与人工授权后的
执行，以保证“建议权”和“执行权”不混在一个组件里。完整定义见
[TECHNICAL_TERMINOLOGY](TECHNICAL_TERMINOLOGY.md)。

模型侧当前只把有界监督 BBox detector 与 Normality development proxy 作为已
存在的本地开发路径。VLM 辅助预标注、样本级 Top-K 挖掘、Active Learning、
TTT 和自动 Mask 生成仍分别保持 `PLANNED_NOT_CONNECTED` 或
`NOT_IMPLEMENTED`，不能从架构图反推为已上线。

## 如何确认手中的版本

源码使用者应同时核对：

1. `git rev-parse HEAD` 的完整 commit SHA；
2. `pyproject.toml`、`web/package.json` 和 Tauri 包元数据；
3. `CHANGELOG.md` 中该提交之前已经落地的变化；
4. 若使用安装包，核对 Release tag、源 commit、`BUILD_MANIFEST.json`、
   `VALIDATION_RECEIPT.json` 和 `SHA256SUMS.txt`；
5. 若核验证据，核对输入分母、运行 namespace、合同版本、JCS 摘要与回执状态；
6. 若查看主仓公开版本，核对 `PUBLIC_MIRROR_MANIFEST.json`（兼容文件名）的 source commit／tree，
   不用网页可访问性替代版本一致性。

## 后续版本更新规则

- 功能代码、README、公开模板和 `CHANGELOG.md` 在同一候选中更新；
- 每个新安装包使用新的 build identity 与回执，不复用旧构建 PASS；
- 先提交源码，再由已提交的 clean tree 生成并机械回填主仓公开面 manifest；
- GitHub source、GitHub Release、Windows 安装、官方提交、客户 shadow 和生产
  放行分别裁决；一个层级的成功不翻转其他层级；
- 完整 Git 历史隐私仍按独立门禁处理，history-free snapshot PASS 不等于完整
  历史已获准公开。

```text
latest_windows_runtime_source=f7f31f7048b14b79990a445f285946f46d3bc41f
latest_windows_candidate=PASS_LOCAL_WINDOWS_CANDIDATE_RELEASE_HOLD
candidate_evidence=docs/WINDOWS_CANDIDATE_F7F31F7_20260916.md
installer_sha256=e32b10cf7e6ac8a9cdeca06b00973c29ff08acec2ae193fbf80c9d0d9a48e826
factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION
official_evaluation=NOT_EVALUATED
production_release_allowed=false
```
