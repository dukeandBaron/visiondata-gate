# 进度板

更新时间：2026-08-13（北京时间）

| 阶段 | 当前状态 | 完成证据 / 剩余边界 |
|---|---|---|
| 选题与边界 | 已完成 | `PROJECT_SPEC.md`、`02_memory/DECISIONS.md`；`PASS` 仅限 `sandbox_experiment_training_pool` |
| 数据合同 | 已完成并验证 | `contracts.py`、严格 schema 与路径校验测试 |
| 程序化数据与四类工具 | 已完成并验证 | 固定 seed、质量/重复泄漏/标注/覆盖工具、隐藏真值 |
| AI Council 与策略 | 已完成并验证 | 五个 AI 角色、共享后端披露、交叉质询、fail-closed policy；不冒充真人专家 |
| 修复复验 | 已完成并验证 | 基础冻结样本 12 份工单；工业治理样本 13 份工单；reserve 模拟修复后均按同合同复验 |
| UI 与报告 | 已完成产品层收口，待最终质量门 | 企业工作台、项目/用户逻辑隔离、真实 REST API、企业 Agent/SaaS 接入入口；四尺寸浏览器 QA 在最终服务进程复验 |
| QA | 待最终回写 | 代码与材料收口后重新运行全量 pytest、Ruff、format、compileall、AppTest 与构包复现；最终计数只从日志回写，symlink 用例在当前 Windows 环境可能明确跳过 |
| 合成压力检查 | 历史冻结通过 | `seed=0..31` 共 `32/32`；仅证明合成内测稳定性 |
| 证据包 | 已冻结 | 9 项 evidence ZIP、内部 manifest 与 SHA-256；不是最终源码提交包 |
| 路演材料 | 终版收口中 | 12 页终版 PPT 已完成；PDF、表单文案、一页纸与 2分50秒脚本按同一 v3 证据锚点收口 |
| 视频 | 技术 QA 通过，画面漂移待终判 | 170.02 秒、H.264 + AAC、5100 帧全解码与 10/10 抽帧通过；若当前产品 UI 与锚点画面不一致则重建并重算哈希 |
| 依赖复现 | 已锁定 | `uv.lock` 已冻结；候选包的干净 Python 3.12.5 复验结果以包外 receipt 为准 |
| 许可与供应链 | 部分闭合 | CycloneDX 1.6 SBOM 与许可证元数据清单已完成；顶层 LICENSE/正式 NOTICE 仍需权利主体确认 |
| AgentTeams v1.2.2 静态接入 | 已实现并验证 | 官方 commit/API 固定；9 个 Worker CR、1 个 Team CR、唯一 Team Leader、Skill 分发计划与 conformance receipt；静态 PASS |
| AgentTeams/Matrix 真实运行 | 外部阻塞 | 本机无 Docker/Podman，WSL 无法挂载，且没有授权模型 API Key；保持 `mapped_not_connected`，不得称为已连接 |
| 声明范围门禁 | 已实现 | `claim_scope_receipt.json` 将本地已验证、合成范围、未验证外部事实与无画面录音转写固化为机器状态 |
| 源码候选包 | 待本轮重建 | 本轮新增 AgentTeams v1.2.2 适配、Claim Scope 与材料更新后必须重新构包、重算 SHA-256；旧 receipt 仅作历史证据 |
| 真实行业验证 | 待外部验证 | 未完成真实客户访谈、真实工业数据评测或现场部署 |
| 官网提交 | 待完成 | 尚未上传最终材料，也没有平台提交回执 |

## 两层运行指标

- 基础四工具冻结样本（`seed=20260809`）：`RECAPTURE / 12 findings → PASS / 0 findings`；Precision / Recall / F1 = `1.0 / 1.0 / 1.0`。
- 工业治理样本（`seed=20260812`）：`RECAPTURE / 13 findings / 13 work orders → PASS / 0 findings`；12 项隐藏真值全部召回，额外 1 条治理 finding 被诚实计作 FP；Precision / Recall / F1 = `0.9231 / 1.0 / 0.96`。
- 两者工单召回率均为 `1.0`，关键坏批次错误发布率均为 `0.0`。

这些指标来自程序化合成隐藏真值，只能证明冻结 Demo 的可复算闭环。最终状态仍以同版本测试日志、产物 manifest、SHA-256、许可材料和官网回执为准；候选包哈希放在包外 receipt，官网回执目前仍不存在。
