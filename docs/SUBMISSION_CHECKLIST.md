# GOAI 赛道二初赛上传清单

作品：VisionData Gate｜工业视觉数据治理与发布 Agent  
赛道：无界应用 Boundless Agents  
方向：AI+工业制造  
Release：`vdg-20260816-rc1`

## P0：任一失败即停止构包/上传

- [x] `tools/check_release_consistency.py` 返回 `ok=true`；
- [x] `release_manifest.json` 的质量门为 `PASS`，测试数量与最终实跑一致；
- [x] ArchBench-v2 为 288 条记录，固定 SOP 负结论保留；
- [x] Omni-180-v1 固定分母 180、1 replan、3 dynamic Workers、45 findings/work orders、8 rule checks PASS；
- [x] 公开 evidence 不含原图、mask、类别名、原文件名和私有绝对路径；
- [x] pytest、Ruff rules、Ruff format、compileall 全部通过；
- [x] 新 PPT/PDF 文件名包含 `BoundlessAgents_20260816`，旧 Agent Infra 路演不进入候选包；
- [x] PPT 全页渲染、逐页检查、overflow/overlap 与模板 fidelity 检查通过；
- [x] PDF 重新解析并逐页渲染检查通过；
- [x] 候选 ZIP 通过 manifest、凭据、路径、哈希、release consistency 和干净解压审计；
- [x] 候选包中不存在旧测试计数、旧 Omni 数据状态或旧主赛道口径；
- [x] Claim Scope 与 UI、README、PPT、表单、QA 报告一致；
- [x] AgentTeams 保持静态 `PASS` / transport `OPEN` / `mapped_not_connected`；
- [x] 不存在客户验收、工厂部署、生产 IAM、外部 LLM、全量 Omni Gate 或官网已提交等虚假表述。

## 初赛上传物

- [x] 作品简介：使用 `docs/submission_form_copy.md` 中“500 字以内作品简介”；
- [x] 方案 PPT：`deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pptx`；
- [x] 方案 PDF：`deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pdf`；
- [x] 可选演示视频策略：RC1 不带旧视频；如需上传，应基于新版 Reviewer Mode 重新录制并单独 QA；
- [x] 源码候选包：`deliverables/VisionData_Gate_GOAI_BoundlessAgents_RC1_20260816.zip`；
- [x] 一页纸：`docs/one_pager.md`；
- [x] 最终 QA：`10_reports/FINAL_QA_REPORT_20260816.md`；
- [x] 包外交付回执：`10_reports/SUBMISSION_DELIVERY_RECEIPT_20260816.json`。

## 账号持有人必须完成

- [ ] 确认报名主体、团队信息和作品名称；
- [ ] 由权利主体选择并确认顶层 LICENSE 与 NOTICE；
- [ ] 在官网上传简介、PPT/PDF、视频和源码链接/附件；
- [ ] 提交前在预览页核对赛道为“赛道二 无界应用”；
- [ ] 保存作品 ID、提交时间、页面截图或平台回执；
- [ ] 将官网回执与本地候选包 SHA-256 对应保存。

本地工程不能替代账号登录、许可证权属判断或官网提交，因此这些项目在完成前不得勾选。
