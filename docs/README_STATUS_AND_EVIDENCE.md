# README 验证与交付状态

## 2026-09-15 公开访问恢复

唯一主仓为 [visiondata-gate](https://github.com/dukeandBaron/visiondata-gate)，[在线 Demo](https://dukeandbaron.github.io/visiondata-gate/) 已完成同仓 Pages 部署。最新核对的成功部署记录为 [34989043847](https://github.com/dukeandBaron/visiondata-gate/actions/runs/34989043847)，对应提交 `df907baa1a107d1d49142f708b20133a0ebe1d4c`；本轮再次读取 Demo 得到 HTTP 200。GitHub API 返回仓库为 Public；本机对 GitHub HTML 的一次匿名 curl 被连接重置，随后全新匿名浏览器实际打开仓库页面成功。这不是完整在线后端或新安装器的验收。

发布前已备份历史并修正分支/标签提交邮箱，逐提交文件树保持一致。GitHub 旧 PR/提交缓存的彻底清除不在普通推送能力范围内。以下表格是此前基线的历史记录，其 Private/历史 HOLD 状态已由本节更新。

本页把产品首页中的能力与其验证范围分开。核对日期：**2026-09-15**；最新 Windows 运行时代码基线：`ca1fa7b1727535014e8723e5bceb4d539272cf2b`。本页及后续发布文档可以位于更晚提交，但不会自动进入该二进制。后续安装器和实验应使用各自回执，不能沿用本页状态。

## 源码、安装器与仓库访问

| 对象 | 本次核对到的状态 | 不能据此推定 |
| --- | --- | --- |
| GitHub 仓库 | 唯一主仓已恢复 Public；仓库和静态 Demo 已有匿名 HTTP 200 证据 | 完整在线后端、当前最新提交已部署或所有外部缓存均已清除 |
| 基线源码 CI | scoped Linux／Windows × Python 3.12／3.13、依赖审计、Bandit、两种语言 CodeQL 分析任务成功；type-debt 为按配置跳过 | 全仓静态类型已通过、所有漏洞均已排除 |
| Windows 候选 | `ca1fa7b` 本地候选已完成构建、提取态、安装启动和发布版登录注册验收；具体摘要见下节 | 正式生产发行、独立干净机或同版本升级验证 |
| 完整 Git 历史隐私 | 公开恢复提交已通过历史重写与 Pages 门禁；后续提交仍需 CI 重新核验 | 一次历史 PASS 可以永久替代后续提交的门禁 |
| 无历史导出快照 | 需要以当前 SHA 绑定的清单独立核验 | 可绕过授权公开私域数据或完整 Git 历史 |
| 工厂、客户与模型效果 | 工业效果／客户验收仍 HOLD；生产放行 false | 客户 ROI、产线 NG 改善、模型达到工业精度 |

CodeQL 分析任务成功与公开 Security 页的告警状态不是同一回事。该候选的发布说明采用 SARIF artifact 留存方式；这里不将任务成功表述为通用安全认证。

## 最新核对的 Windows 候选

最新候选 prerelease 为 [`windows-local-ca1fa7b-20260915`](https://github.com/dukeandBaron/visiondata-gate/releases/tag/windows-local-ca1fa7b-20260915)，源码绑定 `ca1fa7b1727535014e8723e5bceb4d539272cf2b`。完整记录见 [Windows 候选 ca1fa7b](WINDOWS_CANDIDATE_CA1FA7B_20260915.md)。

本次实际重新执行并记录：

- 冻结 350 个源码文件；安装器 SHA-256 为 `09468a0d148017717b2932fc940f17caa378e46fef88ededf582accfea6d05f0`。
- 26 个 PyInstaller PYZ 运行模块与冻结 staged source 匹配。
- 提取态 Spring → FastAPI 请求 `120/120`，两轮 packaged-learning 完成，未使用源码回退。
- NSIS 安装／应用启动／卸载退出码均为 0，SQLite integrity 为 `ok`，卸载收敛完成。
- 正式 Release 构建保持 DevTools 关闭；通过 Windows UI Automation 完成管理员初始化、错误密码恢复、待审批注册、管理员批准、成员登录、重启登录与退出。
- 未签名；独立干净机 `NOT_RUN`；可选 Python／Torch／Ultralytics／权重仍为外部依赖；工厂效果、客户验收和生产放行未取得通过。

内部候选 ZIP、直装 EXE、构建/源码清单、验证摘要/回执和 Release 校验表已经作为同一主仓的 prerelease 附件公开；Release 仍保持 `limited review / RELEASE_HOLD`，不等于正式生产发行。安装步骤和 WebView2 前提见 [Windows 安装说明](WINDOWS_INSTALLER.md)。

此前 `windows-local-dc3a4b-login-fix-20260915` 仍是独立旧候选；它的回执不能替代 `ca1fa7b`，反之亦然。

已记录的 `GHSA-wrw7-89jp-8q8g` 位于 Tauri 的 Linux GTK 依赖链：Windows 目标不编译该依赖，Linux 桌面验证仍保留 HOLD。当前状态以 [质量工具说明](../quality/README.md) 和安全公告为准。

## 实验各自证明什么

| 证据 | 已记录结果 | 适用范围 |
| --- | --- | --- |
| DynamicBench-v3 | Dynamic 正确终态 8/8，Fixed 4/8；工具调用 14 对 24 | 作者定义的固定合成编排场景，外部模型调用为 0；不是外部 Agent 排名或工厂准确率 |
| 独立复杂冲突配对子集 | Dynamic 误放行 0/4，Fixed 4/4 | 独立的四案例子集，不能并入 v3 分母 |
| VisA capsules Normality 开发代理 | 三种子 Image AUROC 均值 0.657823，正常图像 FPR 0.277778，Pixel F1 0.090093 | 开发代理实验；三种子不是三轮动态调优，当前结果不证明工业模型达标 |
| 固定 prompt-injection v2 | 攻击拦截 12/12，良性放行 6/6 | 固定攻击集，不证明未知、自适应或多模态攻击的普适防护 |
| 工厂级误放行／误拦截 | `NOT_MEASURED_PENDING_ADJUDICATION` | 尚不能填写经过独立真值裁决的工厂百分比 |

这些数值来自本次源码基线已有的说明，不是本轮重跑结果。原协议、输入和适用边界见 [DynamicBench-v3](DYNAMICBENCH_V3.md)、[基准复现](BENCHMARK_REPRODUCIBILITY.md)、[证据与实验](EVIDENCE_AND_BENCHMARKS.md) 与 [Claim Scope](CLAIM_SCOPE.md)。私域试跑记录不能替代客户采用证明，也不代表原数据获得再分发授权。

## 页面与截图的真实范围

- README 主图是本地隔离 HTTP 验收期间的真实图像工作簿，截图日期为 2026-09-13；图像来自仓库合成样本，账户名和项目名为测试标识。
- 手动画框与像素灰度／梯度剖面不等于自动缺陷识别、物理设备诊断或模型精度提升。
- 本地服务已连接不等于工厂在线接入；静态 `PUBLIC_SYNTHETIC_REPLAY` 只证明冻结合成回放。即使支持浏览器本地读取图像，也不能据此宣称后台上传、训练或生产服务已部署。
- 本轮只新增一张经像素与 PNG 元数据检查的截图；已有二进制审查条目保持各自内容摘要，未重新签发历史素材或外部证明。

本页没有将未复核的旧 Pages 地址作为可工作的主入口。源码、历史镜像站点和最新安装器应分别辨认。

## 历史参赛材料

2026-09-02 的复赛时间安排和演示脚本作为历史材料保留，不冒充新的决赛规则或当前产品规格：

- [复赛指南核对](GOAI_SEMIFINAL_GUIDE_20260902.md)
- [60 秒演示脚本](DEMO_60S_SCRIPT_SEMIFINAL.md)
- [3 分钟陈述稿](DEFENSE_3MIN_SCRIPT_SEMIFINAL.md)
- [答辩 Q&A](DEFENSE_QA_SEMIFINAL.md)
- [答辩运行手册](SEMIFINAL_DEFENSE_RUNBOOK_20260902.md)

本轮不核验个人赛事上传状态，不以仓库、网页或安装器的可访问性判断是否已提交或获奖。

## 安全与治理

`production_release_allowed=false`；Agent 不替代具名人员的最终决定。本地 SHA-256 能核对完整性，但不是独立签名、可信时间戳或不可重写的历史证明。

详细边界见 [PUBLICATION_BOUNDARY](PUBLICATION_BOUNDARY.md)、[审计信任边界](AUDIT_TRUST_BOUNDARY.md)、[安全策略](../SECURITY.md) 与 [发布准备](RELEASE_PREPARATION.md)。
