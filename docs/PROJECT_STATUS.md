# VisionData Gate｜产品与发布状态

更新时间：2026-08-31

## 当前裁决

```text
development_state=RC3_FROZEN_LOCAL
release_state=LOCAL_RELEASE_CANDIDATE
release_candidate_ready=true
submission_eligible=false
local_release_decision=PASS_LOCAL_RC3_RELEASE_CANDIDATE
official_submission=PENDING
official_evaluation=NOT_EVALUATED
production_release_allowed=false
machine_write_permitted=false
factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION
release_evidence_binding=DETACHED_RELEASE_NAMESPACE_REQUIRED
```

这组状态只表示本地候选代码、材料与可复现实跑已经进入 RC3 封版形态。它不代表官网已经上传、评委已经验收、客户已经采用，或工厂允许生产放行。

`PASS_LOCAL_RC3_RELEASE_CANDIDATE` 只有在完整本地验证集由 verifier 返回 `PASS_LOCAL_INTEGRITY` 时才成立。detached release namespace 必须含 Attestation、两份候选 ZIP、四份 receipt 与 Full JUnit；项目根还必须是匹配的 clean checkout，具有精确 commit/tree、`uv.lock`、SBOM 和 Attestation 声明的本地 toolchain。Attestation 位于 release namespace 根，候选 ZIP 位于其 build 子目录；单独复制“候选 ZIP + Attestation”不能完成复验。本文不复制会随重新封包变化的哈希。任一旁车、checkout 或 toolchain 对账失败时，状态立即退回 `HOLD_AS_RELEASE_TREE`。

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
- `run_semifinal_demo.ps1` 实现 lockfile 固定的 Web 依赖安装、真实本地 API 与精确 `/review?task=...` 深链合同；最终候选能否在全新解压目录稳定启动由包外 post-build smoke 单独判定，本文不预判该结果。

## 仍保持 HOLD / PENDING 的外部事项

- `official_submission=PENDING`：账号持有人尚未取得官网作品 ID、提交时间和平台回执；
- `official_evaluation=NOT_EVALUATED`：没有官方评分或复赛验收结果；
- `factory_shadow_metrics=NOT_MEASURED_PENDING_ADJUDICATION`：没有工厂提供并双人复核的真值分母，因此误放行率、误拦截率和整改后通过率不得填写；
- OpenToken/Gemini、Hosted AgentTeams、CVAT/FiftyOne、OPC UA、MES/QMS、VisionMaster 与工厂 IAM 没有真实成功连接回执；本地合同或 probe gateway 不等于生产集成；
- Windows 安装包仍未签名，也未完成独立 clean-machine 安装/卸载、升级覆盖、可信时间戳或 macOS/Linux 桌面包验证；
- `production_release_allowed=false`、`machine_write_permitted=false` 与 `authority=human_only` 不因本地候选通过而改变。

## 如何独立确认本地候选

1. 对候选 ZIP 计算 SHA-256，并与 detached Release Attestation 的 artifact binding 比对；
2. 运行 `tools/verify_release_attestation.py`，要求返回 `PASS_LOCAL_INTEGRITY`；
3. 在新目录解压候选，执行 `setup_env.ps1` 与 `run_semifinal_demo.ps1`；首次 Web 依赖缺失时入口自动运行锁定的 `npm ci`；
4. 核对 8788 API 与 4180 Web 就绪、精确 Review 深链可打开、Synthetic/Replay/Read-only 标签存在；
5. 任一 required path、manifest、凭据扫描、双构包、JUnit 或 clean-extract 校验失败时，停止提交并恢复 `HOLD_AS_RELEASE_TREE`。

步骤 3–4 是最终 ZIP 的独立 post-build smoke，不属于 Attestation schema。它失败时不改写
`PASS_LOCAL_INTEGRITY` 这一摘要完整性结果，但提交与工作台就绪状态必须保持 HOLD，不能上传。

本地通过不会自动升级官方状态。只有真实平台回执才能改变 `official_submission`，只有官方结果才能改变 `official_evaluation`，只有具名工厂授权与合格证据才能改变生产边界。
