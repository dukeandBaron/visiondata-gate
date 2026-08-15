# Claim Scope｜三级证据与对外用词

本文件规定 VisionData Gate 的对外陈述边界。README、PPT、视频、UI 和答辩都应先陈述已完成事实，再说明外部验收范围；不得把本地证据扩大成第三方背书。

## 第一层：已工程实现 `PASS`

- 本地 Runtime 已接通合同校验、五类工具检查、证据触发 Dynamic Leader、Frozen Policy Judge、整改工单、保留副本修复、同合同复验和证据交付；
- Streamlit 工作台、Reviewer Mode、静态评委网站、REST API、CLI 和 canonical evidence package 均有实际代码与测试；
- finding、work order、rule check、`evidence_span`、`reason_trace` 和 SHA-256 形成统一追踪链；
- Synthetic-v3 在 12 个注入真值问题上验证初始 `RECAPTURE`、修复后 `PASS` 与 F1 1.00；这属于合成工程闭环证据。

## 第二层：已公开数据实跑 `PASS`

- Omni-180-v1 固定 180 张公开图像完成 Policy Gate；
- 中间证据触发 1 次 replan 和 3 个动态 Worker：metadata 数量漂移 15、28 个原生分辨率组、2 个跨工具冲突样本；
- 最终交付 45 条 findings、45 张整改工单、8 项规则检查，结论为 `RECAPTURE`；
- ArchBench-v2 含 288 条同协议记录。三种架构错误放行率均为 0%、成功率与扰动稳定率均为 100%、F1 均为 0.96，因此固定 SOP 下多 Agent 必要性未被支持；
- 公开 release 的 GateResult、dynamic plan、scenario delivery receipt、Omni receipt 与 benchmark 具有交叉 SHA-256 和私有路径扫描。

Omni 源树的 4,464 张图像与 1,439 个 masks 只完成结构/解码审计；全量 Policy Gate 的已验证分母仍为 180。

## 第三层：下一阶段外部验收 `OPEN`

以下事项必须获得对应外部主体、授权环境或平台回执后，才能升级表述：

- 客户/企业 shadow test、客户验收和 ROI；
- 工厂现场只读接入、现场 KPI 和业务责任人确认；
- 生产部署、生产 IAM、SLA/SLO 或自动生产写回；
- 外部 LLM 实际运行与成本回执；
- Omni 4,464 张图像全量 Policy Gate；
- hosted AgentTeams/Matrix transport；当前静态契约为 `PASS`，transport 为 `OPEN`，连接状态为 `mapped_not_connected`；
- 大赛官网作品 ID、上传回执、晋级或获奖；
- 顶层 LICENSE 与 NOTICE 的权利主体确认。

第三层是扩大采用范围所需的下一批证据，不反向否定第一、二层已经完成的工程实现与固定公开数据实跑。

## 允许使用的强陈述

- “已完成训练前工业视觉数据批次审核应用的本地可运行闭环。”
- “已实现工作台、在线评委 Demo、REST API、五类工具、证据触发 Dynamic Leader、Frozen Policy Judge、整改工单、同合同复验与证据包。”
- “已在固定 180 张公开图像上完成 Policy Gate 实跑：1 次重规划、3 个动态 Worker、45 条 findings、45 张整改工单、8 项规则检查，结论 `RECAPTURE`。”
- “已完成 288 条传统流水线、单 Agent、多 Agent 同协议对照；固定 SOP 下多 Agent 必要性未被支持。”

## 需要外部证据后才能使用的表述

- “真实客户已验收”或“已有客户 ROI”；
- “生产级已部署”或“工厂已上线”；
- “外部专家/外部 LLM 已批准”；
- “全量 Omni 已认证”；
- “AgentTeams 已接入”；
- “官网已提交、已晋级或已获奖”。
