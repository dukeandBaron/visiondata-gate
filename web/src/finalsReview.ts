/** GOAI 2026 Track 2 finals: navigation metadata, never a project score. */
export const finalsReview = {
  deadline: "2026-09-20T12:00:00+08:00",
  eventDate: "2026-09-22",
  presentationMinutes: 8,
  questionsMinutes: 5,
  dimensions: [
    { id: "value", title: "问题价值与实际影响", points: 20, href: "/pilot", proof: "目标用户、任务流程、价值来源与场景复制", question: "谁反复需要这项工作，实际改善如何测量，换一个项目怎样复用？", status: "PARTIAL_EXTERNAL_EVIDENCE", boundary: "场景、角色、试点指标与授权离线记录已明确；客户独立使用、工厂 KPI 和跨机构验证仍待外部证据。", criteria: [
      { title: "场景真实性、重要性与高频性", points: 8 },
      { title: "用户/业务价值证据", points: 7 },
      { title: "落地复制与推广潜力", points: 5 },
    ] },
    { id: "innovation", title: "创新性", points: 25, href: "/command-center", proof: "任务交接、证据驱动重规划、双反馈与对照实验", question: "为什么固定脚本不够，Agent 如何因新证据改变下一步并处理失败？", status: "PASS_LOCAL_REPRODUCIBLE", boundary: "动态补证与双反馈可本地复现；不把更换界面、增加角色或调用模型本身写成创新。", criteria: [
      { title: "Agent 任务范式或交互机制创新", points: 10 },
      { title: "Agent 闭环与解决方式创新", points: 10 },
      { title: "相对同类产品/方案的实质差异", points: 5 },
    ] },
    { id: "technology", title: "技术 / 研究深度", points: 25, href: "/evidence", proof: "同一任务调用链、自研边界、权限与证据追溯", question: "状态、规划、工具、人工闸门和结果能否回到同一 Run 与实际代码？", status: "PASS_LOCAL_TRACEABLE", boundary: "核心内核、工具合同和 JCS/SHA 追溯已实现；摘要不是数字签名，外部 Planner 与生产设备连接按实际回执声明。", criteria: [
      { title: "Agent 架构、规划与工具调用", points: 10 },
      { title: "自研贡献与复杂任务处理能力", points: 8 },
      { title: "安全、合规与可追溯设计", points: 7 },
    ] },
    { id: "completion", title: "完成度与可验证性", points: 15, href: "/runs", proof: "真实本地运行、改变输入复验、异常恢复与版本对账", question: "评委更换输入后能否跑通，并对失败、重试、版本和结果逐项对账？", status: "PASS_LOCAL_HOLD_FREEZE", boundary: "本地业务链、公开图像工作簿与 Windows 候选可运行；全仓冻结回归、代码签名和独立干净机仍为 HOLD。", criteria: [
      { title: "核心任务闭环与稳定性", points: 8 },
      { title: "产品体验与结果一致性", points: 7 },
    ] },
    { id: "reuse", title: "开源价值与复用", points: 15, href: "/integrations", proof: "核心代码、Workflow/Skill、部署与复现指南", question: "第三方能否理解、安装、改变输入、复用接口并报告可核验结果？", status: "PASS_PUBLIC_HOLD_THIRD_PARTY", boundary: "核心源码、许可证、示例、Issue 模板和发布记录已公开；独立第三方部署/采用记录仍待取得。", criteria: [
      { title: "核心组件/Workflow/Skill 开放程度", points: 7 },
      { title: "文档、部署、复用与第三方验证", points: 8 },
    ] },
  ],
} as const;
