# README 验证与交付状态

## 2026-09-16 当前源码复现

本轮在独立的 Python 3.12 锁定环境执行新运行，未修改旧基准结果或用户数据：

| 路径 | 本轮结果 | 口径 |
| --- | --- | --- |
| CLI 两种 seed | 各自初检 12 findings，派生复验 0 findings | 合成数据流程；不是两个客户或工厂效果 |
| DynamicBench-v2 | 288 条排序记录通过 | 确定性选择器协议 |
| DynamicBench-v3 | 8 fixtures / 16 records；Dynamic 8/8、Fixed 4/8；双方 unsafe release 均 0 | 新报告封套与原冻结摘要 `6a2b107c20eac5f590d9e36a9bcdb835efd080dc9c456528d18e224831585455` 一致 |
| DynamicBench-v4 | 4/4 实际 ProductService 案件通过；包含工具失败关闭 | 本地产品软件链路；外部模型调用 0 |
| HTTP 学习参考流程 | 两轮完成、FINALIZED | NumPy 参考模型；模拟复核人，不是工业 RL/TTT |
| 全仓 Python 3.12 回归 | 2094 collected；2070 passed；24 skipped；0 failed；0 errors；17 warnings；3067.57s | 单一连续运行，绑定源码 `f7f31f7048b14b79990a445f285946f46d3bc41f`；是本地源码回归，不是外部认证 |

**当前公开源码候选的全仓回归已连续运行到结束。** 24 项 skip 中，19 项依赖未分发的历史私有发行/评审材料，4 项需要当前 Windows 用户不具备的 symlink 权限，1 项需要显式外部 YOLO 运行授权；这些项目没有被写成 PASS。完整命令、分母和边界见 [f7f31f7 全仓回归记录](FULL_REGRESSION_F7F31F7_20260916.md)。公开 CI 仍是明确定义的多平台测试切片，不能用本地全量结果替代 GitHub CI。

以下安装器记录属于最终公开源树 `f7f31f7` 的重新构建与重新验收；没有继承旧 `ca1fa7b` 候选的 PASS。

## 2026-09-15 公开访问恢复

唯一主仓为 [visiondata-gate](https://github.com/dukeandBaron/visiondata-gate)，[在线 Demo](https://dukeandbaron.github.io/visiondata-gate/) 已完成同仓 Pages 部署。公开源码 `f7f31f7048b14b79990a445f285946f46d3bc41f` 的 Pages、工程质量和安全工作流均为 success；Pages 成功记录为 [35064604403](https://github.com/dukeandBaron/visiondata-gate/actions/runs/35064604403)。这仍不是完整在线业务后端。

发布前已备份历史并修正分支/标签提交邮箱，逐提交文件树保持一致。GitHub 旧 PR/提交缓存的彻底清除不在普通推送能力范围内。以下表格是此前基线的历史记录，其 Private/历史 HOLD 状态已由本节更新。

本页把产品首页中的能力与其验证范围分开。核对日期：**2026-09-16**；最新已验证 Windows 运行时代码与全仓回归均绑定 `f7f31f7048b14b79990a445f285946f46d3bc41f`。其后的文档或清单提交不自动进入该二进制。

## 源码、安装器与仓库访问

| 对象 | 本次核对到的状态 | 不能据此推定 |
| --- | --- | --- |
| GitHub 仓库 | 唯一主仓已恢复 Public；仓库和静态 Demo 已有匿名 HTTP 200 证据 | 完整在线后端、当前最新提交已部署或所有外部缓存均已清除 |
| 基线源码 CI | scoped Linux／Windows × Python 3.12／3.13、依赖审计、Bandit、两种语言 CodeQL 分析任务成功；type-debt 为按配置跳过 | 全仓静态类型已通过、所有漏洞均已排除 |
| Windows 候选 | `f7f31f7` 已完成构建、113/113 提取态检查、两轮包内学习、安装启动、七步 UIA 和卸载；具体摘要见下节 | 正式生产发行、独立干净机、同版本升级或代码签名 |
| 完整 Git 历史隐私 | 公开恢复提交已通过历史重写与 Pages 门禁；后续提交仍需 CI 重新核验 | 一次历史 PASS 可以永久替代后续提交的门禁 |
| 无历史导出快照 | 需要以当前 SHA 绑定的清单独立核验 | 可绕过授权公开私域数据或完整 Git 历史 |
| 工厂、客户与模型效果 | 工业效果／客户验收仍 HOLD；生产放行 false | 客户 ROI、产线 NG 改善、模型达到工业精度 |

CodeQL 分析任务成功与公开 Security 页的告警状态不是同一回事。该候选的发布说明采用 SARIF artifact 留存方式；这里不将任务成功表述为通用安全认证。

## 最新核对的 Windows 候选

最新候选 prerelease 为 [`windows-local-f7f31f7-finals-20260916`](https://github.com/dukeandBaron/visiondata-gate/releases/tag/windows-local-f7f31f7-finals-20260916)，源码绑定 `f7f31f7048b14b79990a445f285946f46d3bc41f`。完整记录见 [Windows 候选 f7f31f7](WINDOWS_CANDIDATE_F7F31F7_20260916.md)。

该候选的原始验收实际执行并记录：

- 冻结 355 个源码文件；安装器 SHA-256 为 `e32b10cf7e6ac8a9cdeca06b00973c29ff08acec2ae193fbf80c9d0d9a48e826`。
- 26 个 PyInstaller PYZ 运行模块与冻结 staged source 匹配。
- 提取态 Spring → FastAPI 请求 `113/113`，两轮 packaged-learning 完成，未使用源码回退。
- NSIS 安装／应用启动／卸载退出码均为 0，SQLite integrity 为 `ok`，卸载收敛完成。
- 正式 Release 构建保持 DevTools 关闭；通过 Windows UI Automation 完成管理员初始化、错误密码恢复、待审批注册、管理员批准、成员登录、重启登录与退出。
- 未签名；独立干净机 `NOT_RUN`；可选 Python／Torch／Ultralytics／权重仍为外部依赖；工厂效果、客户验收和生产放行未取得通过。

内部候选 ZIP、直装 EXE、构建/源码清单、验证摘要/回执和 Release 校验表已经作为同一主仓的 prerelease 附件公开；Release 仍保持 `limited review / RELEASE_HOLD`，不等于正式生产发行。安装步骤和 WebView2 前提见 [Windows 安装说明](WINDOWS_INSTALLER.md)。

此前 `ca1fa7b`、`dc3a4b` 和 `ce72604` 均为独立历史候选；其回执不能替代 `f7f31f7`，反之亦然。

已记录的 `GHSA-wrw7-89jp-8q8g` 位于 Tauri 的 Linux GTK 依赖链：Windows 目标不编译该依赖，Linux 桌面验证仍保留 HOLD。当前状态以 [质量工具说明](../quality/README.md) 和安全公告为准。

## 实验各自证明什么

| 证据 | 已记录结果 | 适用范围 |
| --- | --- | --- |
| DynamicBench-v3 | Dynamic 正确终态 8/8，Fixed 4/8；工具调用 14 对 24 | 作者定义的固定合成编排场景，外部模型调用为 0；不是外部 Agent 排名或工厂准确率 |
| 独立复杂冲突配对子集 | Dynamic 误放行 0/4，Fixed 4/4 | 独立的四案例子集，不能并入 v3 分母 |
| VisA capsules Normality 开发代理 | 三种子 Image AUROC 均值 0.657823，正常图像 FPR 0.277778，Pixel F1 0.090093 | 开发代理实验；三种子不是三轮动态调优，当前结果不证明工业模型达标 |
| 异常 Operating Point 源码组件 | `SOURCE_COMPONENT_TESTED / PRODUCT_API_NOT_CONNECTED` | calibration 与 heldout-development 合同和算法专项已测；fresh external run、产品 API、工业阈值与生产批准均未完成 |
| 固定 prompt-injection v2 | 攻击拦截 12/12，良性放行 6/6 | 固定攻击集，不证明未知、自适应或多模态攻击的普适防护 |
| 工厂级误放行／误拦截 | `NOT_MEASURED_PENDING_ADJUDICATION` | 尚不能填写经过独立真值裁决的工厂百分比 |

这些数值来自本次源码基线已有的说明，不是本轮重跑结果。原协议、输入和适用边界见 [DynamicBench-v3](DYNAMICBENCH_V3.md)、[基准复现](BENCHMARK_REPRODUCIBILITY.md)、[证据与实验](EVIDENCE_AND_BENCHMARKS.md) 与 [Claim Scope](CLAIM_SCOPE.md)。私域试跑记录不能替代客户采用证明，也不代表原数据获得再分发授权。

## 页面与截图的真实范围

- README 主图是本地隔离 HTTP 验收期间的真实图像工作簿，截图日期为 2026-09-13；图像来自仓库合成样本，账户名和项目名为测试标识。
- 手动画框与像素灰度／梯度剖面不等于自动缺陷识别、物理设备诊断或模型精度提升。
- 本地服务已连接不等于工厂在线接入；静态 `PUBLIC_SYNTHETIC_REPLAY` 只证明冻结合成回放。即使支持浏览器本地读取图像，也不能据此宣称后台上传、训练或生产服务已部署。
- 本轮只新增一张经像素与 PNG 元数据检查的截图；已有二进制审查条目保持各自内容摘要，未重新签发历史素材或外部证明。

本页没有将未复核的旧 Pages 地址作为可工作的主入口。源码、历史镜像站点和最新安装器应分别辨认。

## 材料与运行版本

历史演示时长与脚本不定义当前产品能力。第三方运行请以 [复现指南](LIVE_REPRODUCTION.md)、所选源码提交和安装包各自的版本清单为准。仓库、网页或安装器可访问不代表个人赛事表单已提交，也不构成客户验收。

## 安全与治理

`production_release_allowed=false`；Agent 不替代具名人员的最终决定。本地 SHA-256 能核对完整性，但不是独立签名、可信时间戳或不可重写的历史证明。

详细边界见 [PUBLICATION_BOUNDARY](PUBLICATION_BOUNDARY.md)、[审计信任边界](AUDIT_TRUST_BOUNDARY.md)、[安全策略](../SECURITY.md) 与 [发布准备](RELEASE_PREPARATION.md)。
