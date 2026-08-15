# VisionData Gate 最终工程 QA 报告

核验日期：2026-08-13（北京时间）。机器可读锚点：`10_reports/FINAL_QA_REPORT_20260813.json`。

## 结论

VisionData Gate 当前定位为 **面向 AI 数据生产链的可信 Agent Runtime 与治理协议**；工业视觉数据发布门禁是首个行业 Adapter。产品层提供团队工作台、项目/用户逻辑隔离、本地 REST API，以及企业 Agent、SaaS 和内部流水线三类接入入口。三类入口复用同一 `ProductService`、SQLite 状态和不可变任务证据，不是三套演示逻辑。

当前状态是本地工程候选，不是生产 SaaS：没有真实客户、真实工业数据验证、生产 IAM/部署、hosted AgentTeams/Matrix 运行回执或官网提交回执。`PASS` 只允许批次进入 `sandbox_experiment_training_pool`。

## 本轮收口

- 产品主路径：工作台创建任务 → 生命周期与 append-only events → finding → 工单 → 同规则复验 → trace/evidence 交付。
- 接入思路：浏览器工作台、`POST /v1/tasks` 企业 Agent 调用、SaaS/流水线下载 trace 和 evidence ZIP。
- API 安全边界：默认不公开账户创建/枚举；工作区 actor/owner 一致；任务幂等；跨工作区隐藏；下载前 SHA-256 复核；统一错误 envelope。
- UI：普通用户只看到工作台、项目、审核记录、能力目录、API 接入与安全权限；竞赛审计和协议明细在高级区按需加载。
- 构包：提交媒体和 QA 报告改为 allowlist，排除历史视频、旧路演稿、渲染预览、浏览器痕迹、历史 QA 脚本/日志与 detached receipt。

## 可复算锚点

- 工业治理样本：`RECAPTURE / 13 findings / 13 work orders → PASS / 0 findings`。
- 隐藏真值：12/12 召回；额外 1 条治理重叠 finding 显式计为 FP；Precision 0.9231 / Recall 1.0 / F1 0.96。
- Runtime：24 tasks / 37 events / 31 ContextTransfer；10/10 工具消融均转为 `DEFER`，无更宽松结果。
- 负路径：相同输入、合同、策略下，缺 Worker 为 `DEFER → DEFER`，0 假修复。
- AgentTeams：v1.2.2 静态契约 `PASS`；真实 Team/Matrix transport 为 `mapped_not_connected`。

## 质量门说明

工程全量门为 `143 passed / 1 skipped / 0 failed`；唯一跳过项是当前 Windows 环境不可创建文件 symlink。`uv lock --check`、55 包 dry-run、Ruff 规则/格式与 compileall 均通过。四档浏览器视口无横向溢出，控制台 `0 error / 0 warning`；审核记录证据链渲染 13 张卡，安全与权限页默认折叠评审状态。

真实本地 HTTP 进程完成 `202 Accepted → 37 条连续事件 → trace/evidence`，任务幂等与响应 SHA-256 均复核通过；该结果记录在 `10_reports/API_SMOKE_20260813.json`，不是客户或生产部署证据。

候选 ZIP 的精确字节数、SHA-256、双构建一致性、敌意归档审计和 exact-package cleanroom 结果只记录在包外 detached receipt，避免包内报告产生自引用哈希。若任一门禁未通过，候选包不得标为可上传。

视频 `deliverables/VisionDataGate_GOAI_FinalDemo_20260813.mp4` 已通过 170.02 秒、1920×1080、30 fps、H.264/AAC、5100 帧全解码、10/10 场景抽帧与匿名扫描。新版首场景使用当前企业工作台，第七场景使用当前 API 接入页；其余 Runtime、证据、失败语义与声明边界沿用已验证素材。视频为本地合成工程演示，不是客户或生产证据。

## 外部边界

- Omni/海康数据尚未读取、复制或打包；接入需先确认绝对路径、权利主体、用途、驻留、脱敏和公开包权限。
- 1111 是录音转写，没有可核验画面；钉钉登录保护回放未被直接验证。
- 顶层 LICENSE/正式 NOTICE 仍需权利主体确认。
- 官网上传、作品 ID 和提交回执只能由账号持有人完成。
