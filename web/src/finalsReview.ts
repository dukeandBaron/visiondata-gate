/** GOAI 2026 Track 2 finals: navigation metadata, never a project score. */
export const finalsReview = {
  deadline: "2026-09-20T12:00:00+08:00",
  eventDate: "2026-09-22",
  presentationMinutes: 8,
  questionsMinutes: 5,
  dimensions: [
    { title: "问题价值与实际影响", points: 20, href: "/review", proof: "目标用户、任务流程、价值来源与场景复制", criteria: [
      { title: "场景真实性、重要性与高频性", points: 8 },
      { title: "用户/业务价值证据", points: 7 },
      { title: "落地复制与推广潜力", points: 5 },
    ] },
    { title: "创新性", points: 25, href: "/command-center", proof: "任务交接、证据驱动重规划、双反馈与对照实验", criteria: [
      { title: "Agent 任务范式或交互机制创新", points: 10 },
      { title: "Agent 闭环与解决方式创新", points: 10 },
      { title: "相对同类产品/方案的实质差异", points: 5 },
    ] },
    { title: "技术 / 研究深度", points: 25, href: "/evidence", proof: "同一任务调用链、自研边界、权限与证据追溯", criteria: [
      { title: "Agent 架构、规划与工具调用", points: 10 },
      { title: "自研贡献与复杂任务处理能力", points: 8 },
      { title: "安全、合规与可追溯设计", points: 7 },
    ] },
    { title: "完成度与可验证性", points: 15, href: "/runs", proof: "真实本地运行、改变输入复验、异常恢复与版本对账", criteria: [
      { title: "核心任务闭环与稳定性", points: 8 },
      { title: "产品体验与结果一致性", points: 7 },
    ] },
    { title: "开源价值与复用", points: 15, href: "/integrations", proof: "核心代码、Workflow/Skill、部署与复现指南", criteria: [
      { title: "核心组件/Workflow/Skill 开放程度", points: 7 },
      { title: "文档、部署、复用与第三方验证", points: 8 },
    ] },
  ],
} as const;
