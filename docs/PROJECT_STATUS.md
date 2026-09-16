# VisionData Gate｜产品与发布状态

更新时间：2026-09-16

## 当前裁决

```text
current_worktree_state=PUBLIC_MAIN_FINALS_CLOSURE
source_validation_anchor=f7f31f7048b14b79990a445f285946f46d3bc41f
source_tree=539fad43bc7074991d516539748bb2f9fa9e08dc
source_full_pytest=PASS_2070_PASSED_24_SKIPPED_0_FAILED_0_ERRORS
current_release_decision=PASS_LIMITED_REVIEW_PRERELEASE
canonical_repository=dukeandBaron/visiondata-gate
canonical_repository_visibility=PUBLIC
public_pages_mode=PUBLIC_SYNTHETIC_REPLAY
online_demo=PASS_PUBLIC_STATIC_BROWSER_LOCAL_MEASUREMENT
online_backend_deployment=NOT_DEPLOYED
latest_verified_windows_source=f7f31f7048b14b79990a445f285946f46d3bc41f
windows_candidate=BUILT_VALIDATED_AND_PUBLISHED_AS_PRERELEASE
windows_release_tag=windows-local-f7f31f7-finals-20260916
installer_sha256=e32b10cf7e6ac8a9cdeca06b00973c29ff08acec2ae193fbf80c9d0d9a48e826
code_signed=false
clean_machine_validation=NOT_RUN
same_version_upgrade_validation=NOT_RUN
finals_non_ppt_materials=PASS_LOCAL_READY
official_finals_form_submission=PENDING_ACCOUNT_HOLDER_RECEIPT
official_evaluation=NOT_EVALUATED
production_release_allowed=false
machine_write_permitted=false
factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION
release_evidence_binding=BOUND_TO_F7F31F7_MANIFESTS_AND_SHA256
public_distribution=PUBLIC_SOURCE_AND_LIMITED_REVIEW_PRERELEASE
```

最终公开源树 `f7f31f7` 在 Python 3.12 锁定环境中完成一次连续全仓回归：2094 项收集、2070 passed、24 skipped、0 failed、0 errors、17 warnings，耗时 3067.57 秒。24 项 skip 分别对应 19 项未随公共仓分发的历史私有发行输入、4 项 Windows 当前用户无 symlink 权限和 1 项未授权的外部 YOLO 运行时；这些能力没有计入 PASS。详见 [最终全仓回归记录](FULL_REGRESSION_F7F31F7_20260916.md)。源码回归不自动升级 Pages、安装器、客户验收或生产放行。

同一源树已经生成并公开 Windows limited-review prerelease [`windows-local-f7f31f7-finals-20260916`](https://github.com/dukeandBaron/visiondata-gate/releases/tag/windows-local-f7f31f7-finals-20260916)。候选完成 26 个 PYZ 模块源码匹配、113/113 提取态 HTTP 检查、两轮 packaged-learning、NSIS 实装/启动/卸载、SQLite integrity 和七步 Tauri UIA；安装器 SHA-256 为 `e32b10cf7e6ac8a9cdeca06b00973c29ff08acec2ae193fbf80c9d0d9a48e826`。它仍未签名，未完成独立干净机或同版本升级验证，因此不是生产发行。详见 [最终 Windows 候选记录](WINDOWS_CANDIDATE_F7F31F7_20260916.md)。

公开交付只使用唯一主仓 `dukeandBaron/visiondata-gate`：本地完整工作区中的私域运行证据、原始 Omni/CAPA 资产、密钥、本机路径和未审查材料不进入 Git；主仓保留允许公开的源码、合成样本、锁文件、文档与静态 `PUBLIC_SYNTHETIC_REPLAY`。主仓和 Pages 是否与当前候选一致，必须同时核对 `PUBLIC_MIRROR_MANIFEST.json`（兼容文件名）的 source commit/tree 与部署 SHA。

旧 RC3／RC4、`ca1fa7b` 与 `9417f01` 记录继续作为不可变历史证据保留，但不能替代 `f7f31f7` 候选。当前候选的源码、构建清单、验证摘要、回归聚合回执和 SHA-256 已绑定到同一 GitHub prerelease；原始 JUnit 含本机绝对路径，只公开其摘要与原始文件哈希。其后的 README、清单或开源文档提交不会自动进入既有二进制。

## 当前主版本

- 主执行内核：`Industrial Incident v6`，生命周期为 Intake → Planner → Tool → Council/Ledger → Policy Judge → Delivery；
- 决策交付：`DecisionPacket v3` 与 `GovernedOutcomeEnvelope v1`；
- Worker 选择证据：`DynamicBench-v2`，只证明冻结排序、预算和输入顺序稳定性；
- 编排优势证据：`DynamicBench-v3`，只证明冻结合成冲突、故障和不确定性夹具；
- 产品路径证据：`DynamicBench-v4`，证明样例实际穿越 ProductService → Incident v6；
- v1–v5 仅作为不可变历史案件回放兼容层，不作为当前主执行版本。

## 已确认成立

- 授权本地 Product Kernel 已贯通 `ProductService → Agent Core → Evidence ZIP`，生产入口、Synthetic Demo 与 Validation Harness 分离；
- Planner 依据竞争假设、缺失证据、triggering evidence 和冻结预算选择白名单 Worker，并同时保存 selected/rejected 理由；
- Reviewer/Case Workbench 读取真实本地 API 投影，复核 ETag、`X-Content-SHA256` 与工件 JCS SHA-256；读取失败保留上一份已验证事实并显式进入 stale/contract/retryable HOLD；
- Parent Case、具名人工决定、CAPA 私有派生版本、Child Run、责任队列与 Interaction Receipt 已形成可恢复深链；
- 五类浏览器负向场景均观察到预期失败关闭：原因码缺失、Agent 行为哈希错误、强 ETag 漂移、网络中断和旧投影冲突；页面写请求为 0，未制造 PASS；
- CAPA 派生版本使用同卷 staging、回读校验与不覆盖目标的原子目录发布；该原子性不扩大到数据库、授权、Child Run 或生产系统；
- `GovernedOutcomeEnvelope v1` 将 12 类闭环工件汇总为 tamper-evident 本地投影；数字签名、可信时间戳和外部锚仍未配置；
- 公开候选只包含可再分发的合成/脱敏证据。私域 Omni/CAPA 原始回执、图像、mask、本机路径、密钥和客户身份不进入公开包；
- `run_semifinal_demo.ps1` 实现 lockfile 固定的 Web 依赖安装、真实本地 API 与精确 `/review?task=...` 深链合同；最终候选已经完成提取态 HTTP、实际安装启动、七步 UIA 与卸载验收，但独立第三方干净机仍为 `NOT_RUN`。

## 仍保持 HOLD / PENDING 的外部事项

- `official_submission=PENDING`：账号持有人尚未取得官网作品 ID、提交时间和平台回执；
- `official_evaluation=NOT_EVALUATED`：没有官方评分或复赛验收结果；
- `factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION`：没有工厂提供并双人复核的真值分母，因此误放行率、误拦截率和整改后通过率不得填写；
- OpenToken/Gemini、Hosted AgentTeams、CVAT/FiftyOne、OPC UA、MES/QMS、VisionMaster 与工厂 IAM 没有真实成功连接回执；本地合同或 probe gateway 不等于生产集成；
- Windows 安装包仍未签名，也未完成独立 clean-machine、同版本升级、可信时间戳或 macOS/Linux 桌面包验证；
- `production_release_allowed=false`、`machine_write_permitted=false` 与 `authority=human_only` 不因本地候选通过而改变。

## 如何独立确认当前候选

1. 从当前 prerelease 下载候选 ZIP／EXE 与 `RELEASE_SHA256SUMS.txt`，先核对 SHA-256；
2. 核对 `SOURCE_MANIFEST.json`、`BUILD_MANIFEST.json`、`VALIDATION_SUMMARY.json` 与 `VALIDATION_RECEIPT.json` 的绑定；
3. 在隔离目录解压候选，或在 Windows 测试机安装后启动；首次使用外部可选模型时另行登记环境、权重和许可证；
4. 核对本地网关、FastAPI、账户登录、项目与 Review 深链，并确认页面没有把 Pages 合成回放写成业务后端结果；
5. 任一必需文件、清单、凭据扫描、安装启动或哈希对账失败时，停止使用并保持 `RELEASE_HOLD`。

本机已完成的安装/UIA/卸载验证不能替代独立第三方 clean-machine 证据。后者缺失时可将候选用于受限评审与复现，不能将其描述为生产就绪。

本地通过不会自动升级官方状态。只有真实平台回执才能改变 `official_submission`，只有官方结果才能改变 `official_evaluation`，只有具名工厂授权与合格证据才能改变生产边界。
