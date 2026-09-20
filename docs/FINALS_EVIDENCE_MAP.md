# GOAI 赛道二决赛证据索引

本页按 2026 年决赛规则的 100 分结构整理可核验入口。它不预测得分，也不将规划、合成实验或本地验证升级为客户采用和生产效果。

## 一、问题价值与实际影响 20 分

| 二级考核点 | 分值 | 当前证据 | 仍缺什么 |
| --- | ---: | --- | --- |
| 场景真实性、重要性与高频性 | 8 | README 的目标用户、换型/返修流程；[行业场景价值](INDUSTRY_SCENARIO_VALUE.md) | 独立客户访谈与真实任务频次原始记录仍需封版前核验 |
| 用户/业务价值证据 | 7 | 运行日志、版本/责任闭环、历史授权离线试跑；模拟/私域边界已声明 | 客户时间/成本/质量改善与对照基线 `NOT_MEASURED` |
| 落地复制与推广潜力 | 5 | Rule Pack、Schema、Adapter、Skill 与 Site Pack 说明不变量/替换项 | 第二个独立机构按文档采用记录尚未取得 |

## 二、创新性 25 分

| 二级考核点 | 分值 | 当前证据 | 适用边界 |
| --- | ---: | --- | --- |
| Agent 任务范式或交互机制 | 10 | [三阶段、五功能和双反馈](TECHNICAL_TERMINOLOGY.md)；工作簿到案件/整改的交互 | 不是用角色数量证明创新 |
| Agent 闭环与解决方式 | 10 | Parent/Human/Derived/Child；诊断修订与整改修订；失败/中断恢复 | 完成执行不等于 Gate PASS 或生产批准 |
| 相对同类方案差异 | 5 | 固定 SOP 负结论、DynamicBench-v3 编排对照、v4 产品运行链；[开源方案比较](AGENT_PLATFORM_COMPARISON.md) | v3/v4 分母与证明对象不同；未实跑的外部框架不写成对照结果 |

## 三、技术与研究深度 25 分

| 二级考核点 | 分值 | 当前证据 | 核验入口 |
| --- | ---: | --- | --- |
| 架构、规划与工具调用 | 10 | 证据缺口、Worker 选择/拒绝、预算、ToolTrace、DecisionPacket | [技术总览](PROJECT_TECHNICAL_OVERVIEW.md) · [Agent 架构](AGENT_PLATFORM.md) |
| 自研贡献与复杂任务 | 8 | 合同、规则、编排、CAPA/复验、学习身份与异常恢复；AI 辅助开发披露 | [自研与第三方](DEVELOPMENT_PROVENANCE.md) · `src/visiondata_gate/` |
| 安全、合规与追溯 | 7 | 本地身份/权限、人工闸门、私域边界、JCS/SHA、审计与第三方依赖披露 | [安全策略](../SECURITY.md) · [审计信任边界](AUDIT_TRUST_BOUNDARY.md) |

## 四、完成度与可验证性 15 分

| 二级考核点 | 分值 | 当前证据 | HOLD |
| --- | ---: | --- | --- |
| 核心任务闭环与稳定性 | 8 | [现场重跑](LIVE_REPRODUCTION.md)、DynamicBench、全仓回归、Windows 候选回执 | 评委指定陌生输入仍需现场实跑；独立干净机未验证 |
| 产品体验与结果一致性 | 7 | 在线合成体验、本地工作台、[逐模块能力状态](CAPABILITY_STATUS.md)、源码/安装器/回执身份 | 技术包可独立冻结；PPT 尚未定稿，不据此阻塞技术修复，也不提前声明已对齐 |

## 五、开源价值与复用 15 分

| 二级考核点 | 分值 | 当前证据 | 当前缺口 |
| --- | ---: | --- | --- |
| 核心组件、Workflow、Skill 开放 | 7 | Public 主仓、[核心代码地图](../src/visiondata_gate/README.md)、[Skill](../skills/README.md)、[Schema](../schemas/README.md)、[复用示例](../examples/reuse/README.md)、三组件 `open-reuse` 聚合回执 | 核心自有代码已可访问；外部模型/权重和私域材料不属于开放范围，文本 Skill 不冒充已安装插件 |
| 文档、部署、版本、第三方验证 | 8 | README、[采用指南](ADOPTION_GUIDE.md)、Quickstart、License、接口文档、贡献/Issue/PR 模板、版本记录，以及 Windows/Linux clean-checkout 维护者 CI | 维护者 CI 不等于外部采用；独立第三方结果保持 `THIRD_PARTY_REPRODUCTION_PENDING`，按[复现模板](THIRD_PARTY_REPRODUCTION.md)验收 |

## 封版前必须处理的公开复用风险

### 可以直接抽查的代码与测试

| 要核实的能力 | 实际入口 | 可重跑的验证 |
| --- | --- | --- |
| 输入与人工标注是否真正进入检查 | `operator_snapshot.py`、`product_runs.py` | `tests/test_operator_snapshot_source.py`；覆盖版本漂移、越权和源文件变化 |
| 整改是否真的改变派生数据 | `capa.py` | 同文件中 `test_exact_duplicate_capa_removes_only_derived_copy_and_child_rechecks`；核对父不变、子减少、重新测量 |
| 失败恢复是否只是重播成功结果 | `capa.py` 与 Web 对账锁 | `test_exact_duplicate_capa_resumes_published_subset_and_verifies_binding`；`tests/web_vision_model_workbench.browser.mjs` |
| Agent 是否实际调用与保存状态 | `incident_agent_kernel.py`、`worker_selection.py` | `tools/run_dynamic_benchmark_v4.py` 新目录运行，读取同一 Case 的 Worker 与 DecisionPacket |
| 模型路线是否混写 | `learning_service.py`、`local_model_registry.py` | `tools/run_learning_demo.py` 为 NumPy 参考闭环；Normality/YOLO 另按各自 API 与环境验收 |
| TTT 是否真的更新参数 | `normality_ttt.py`、`normality_adaptation_service.py` | [损失、参数与参考组协议](NORMALITY_TTT.md)；真实 pack 完成 3 步、16 图前后结果不变，不能外推质量提升 |
| 模型反馈是否能转成待办 | `normality_followup_service.py`、真实工作簿与工单存储 | `tests/test_normality_followup.py`；独立授权导入、人工框保存、OPEN 工单及中断对账，不自动关闭责任 |
| 前端是否只靠静态样例 | 模型中心的登记/批准/推理表单 | Node 合同测试与真实浏览器测试验证界面；替身 API 不作真实模型推理证据；真实后端另由 Python/API 测试核验 |
| 来源和发布物是否一致 | `tools/build_finals_technical_bundle.py` | 双构包、ZIP/解压清单核验、独立保存 SHA；完整性不等于功能或安装验收 |

既有测试记录有各自源码范围。本轮新增的运行回执应随提交包按清单绑定；未跑的测试和未重建的二进制不能引用别轮 PASS。[技术包说明](TECHNICAL_SUBMISSION_BUNDLE.md)

决赛规则明确将“仓库公开可访问”列为核心组件开放的重点证据，并要求第三方能理解、部署、运行、复用和继续开发。当前仓库已经 Public，但尚无独立第三方 clean-clone／部署成功记录；这部分不能仅凭维护者自测写成完成。公开状态也不授权暴露客户数据、密钥、私域回执或未审查历史。

`open-reuse` 的 GitHub Actions 从新的 checkout 执行 Skill、Rule Pack 和 Adapter 三条公共合同，属于“公开材料可由维护者 CI 重建”的证据。只有与维护者独立的人员或机构，按照模板提交精确 commit/tree、环境、命令、退出状态和输出摘要，才能把第三方复现状态从 PENDING 改为成功或部分成功。Star、Fork 和仓库创建时间不单独替代这份证据。

规则同时要求 PPT、Demo、代码、运行结果和陈述一致，并允许评委改变输入现场重跑。封版时应保存：唯一 commit/tree、安装器/视频/PPT/一页纸摘要、现场 Run/Case 身份和失败恢复证据。
