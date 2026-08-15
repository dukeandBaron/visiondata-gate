# VisionData Gate 2 分 50 秒新版演示脚本

赛道：GOAI 赛道二“无界应用 Boundless Agents” · AI+工业制造。主角是工业视觉数据治理与发布 Agent，Infra 只作为可信后台。

RC1 默认不把旧视频放入候选包。若录制新版视频，必须完全按下列 Reviewer Mode 与应用闭环重新录制并生成独立 QA；不得把 2026-08-13 的旧叙事视频标为新版。

## 0:00-0:20｜用户、痛点与交付物

画面：工作台首页，再进入“评审模式”首屏。

讲稿：

> VisionData Gate 面向工业视觉算法工程师和数据治理团队。一个图像批次进入训练前，质量、重复、标注、覆盖和治理结果往往散落在不同脚本里。我们交付的不是一句问答，而是 Gate 结论、整改工单、同规则复验和可校验凭证。

## 0:20-0:45｜六步应用闭环

画面：Reviewer Mode 六步闭环；切到工作台创建审核任务。

讲稿：

> 用户提交批次与审核目标后，系统先校验合同和权限，再并行调用五类只读工具。中间证据决定是否补证；Policy Judge 生成门禁结论和工单；整改只发生在保留副本上，之后按原合同复验并交付证据。

## 0:45-1:18｜Dynamic Leader Canvas

画面：Omni-180-v1 Canvas 和三条动态分支表。

讲稿：

> 这里不是固定 DAG。180 张固定公开图像的第一轮检查发现 metadata 与文件树差 15、28 个原生分辨率组，以及 2 个跨工具冲突样本。Leader 在首次裁决之后发生一次重规划，动态增派三个 Worker，分别做元数据对账、分辨率分组补证和冲突复核，然后再次交给 Judge。

## 1:18-1:43｜结论、工单与证据追踪

画面：审核记录详情、findings、work orders、rule checks 和证据下载。

讲稿：

> 最终结论是 RECAPTURE，共 45 条 finding 和 45 张工单，其中 2 条转 INVESTIGATE。每个问题都能追到工具、规则、工单、evidence span 和 reason trace；证据包带 SHA-256，缺失或篡改会失败关闭。

## 1:43-2:05｜企业 Agent / SaaS / API

画面：工作台三个入口和 API 接入页。

讲稿：

> 同一服务层支持团队工作台、企业 Agent API 和 SaaS/数据流水线嵌入。上游创建任务后可查询状态、事件和 trace，并下载证据；本地 Header 只演示工作区隔离，不冒充生产登录或 IAM。

## 2:05-2:30｜为什么不是多角色包装

画面：ArchBench-v2 表格与蓝色负结论卡。

讲稿：

> 我们先用 288 条同协议记录比较传统流水线、单 Agent 和多 Agent。三者错误放行率都是 0%，成功率和扰动稳定率都是 100%，F1 都是 0.96。固定 SOP 下多 Agent 没有优势，所以我们只在中间证据真正改变后续任务时使用动态多 Agent。

## 2:30-2:50｜边界收口

画面：Claim Scope 折叠区。

讲稿：

> 本版本是本地 deterministic runtime，实际模型调用为 0。Omni 的 Policy Gate 只覆盖固定 180，不是客户现场或全量认证。AgentTeams 静态契约通过，但 hosted transport 未连接，状态保持 mapped_not_connected。生产写回始终需要真实授权主体。

## 录制前硬门

- UI 必须显示 `vdg-20260816-rc1` 且 release consistency 通过；
- 最终 QA、PPT/PDF 和候选包必须来自同一 release；
- 录制中不出现私有路径、原图/类别名、终端密钥或本地用户名；
- 不说真实客户、工厂部署、外部 LLM、全量 Omni Gate、AgentTeams 已连接或官网已提交；
- 录制后至少完成全帧解码、分段抽帧、分辨率/帧率/音轨检查和匿名扫描；
- 通过前不把视频加入 `SUBMISSION_DELIVERABLE_ALLOWLIST`。
