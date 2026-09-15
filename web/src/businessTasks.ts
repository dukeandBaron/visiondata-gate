import { finalsReview } from "./finalsReview.ts";

export const scoringCriteria = finalsReview.dimensions.map((dimension) => ({
  id: dimension.id,
  name: dimension.title,
  weight: `${dimension.points} 分`,
  question: dimension.question,
  status: dimension.status,
  boundary: dimension.boundary,
}));

export type BusinessTaskId = "dataset-acceptance" | "annotation-rework" | "dataset-reuse";
type ScoreId = (typeof scoringCriteria)[number]["id"];
export interface BusinessTask {
  id: BusinessTaskId;
  title: string;
  tag: string;
  buyer: string;
  user: string;
  trigger: string;
  outcome: string;
  inputs: string[];
  limitations: string[];
  steps: { title: string; person: string; detail: string; output: string; href: string; action: string }[];
  proof: Record<ScoreId, string>;
}

export const businessTasks: BusinessTask[] = [
  {
    id: "dataset-acceptance", title: "交付前检查一批数据", tag: "首个完整工作任务",
    buyer: "AI 视觉方案商的技术 / 交付负责人", user: "算法工程师与数据交付负责人",
    trigger: "收到新采集、标注交付或修订批次，需要决定接收、退回整改还是保留未解决项。",
    outcome: "技术预检记录、可执行问题单、新版本检查结果或未解决清单；客户接受需另行确认。",
    inputs: ["授权图像与对应标注（如该任务要求标注）", "本次用途、验收标准与必要的划分信息", "数据负责人、复核负责人和原流程基线"],
    limitations: ["新版冻结前可逐样本声明 train/val/test；历史 v1 仍按原始 train 合同回放，不能倒推为已检查跨集泄漏。", "新版必须明确每张图的标注要求并绑定具名复核版本；未知要求、必需标注缺失或不适用冲突会阻止冻结。语义正确性仍需专业人员判断。", "技术预检、客户接受与生产放行分别确认；算力交接只准备沙箱作业元数据，未提交外部 NPU 作业。"],
    steps: [
      { title: "确认交付范围", person: "交付负责人", detail: "固定输入范围、用途和接受条件，记录谁负责处理问题、谁复核。", output: "批次范围与待确认条件", href: "/pilot", action: "约定试点范围" },
      { title: "导入并检查数据", person: "视觉工程师", detail: "导入图像、标注并冻结快照；用工具检查质量、重复和标注风险。", output: "输入版本、测量与问题证据", href: "/workspace", action: "打开图像工作簿" },
      { title: "批准适用的整改", person: "负责人", detail: "区分工具可处理问题和仍需调查事项，按明确范围选择和批准整改。", output: "问题责任与批准范围", href: "/capa", action: "查看整改工作台" },
      { title: "复验并交付", person: "复核人", detail: "原版本保留，新版本按同一合同复验；正确阻断并交接完整问题单也可完成预检任务，不代表整改已完成。", output: "复验结果或未解决清单", href: "/lineage", action: "查看版本与复验" },
    ],
    proof: {
      value: "比较每批人工有效工时和整改往返；用第二批或第二项目验证重复使用。",
      innovation: "普通检查由工具执行；复杂 Incident 才按新证据改变 Worker 与后续任务，并保留两类修订回路。",
      technology: "冻结快照、Parent、具名批准、派生版本与 Child Run 由同一任务身份和摘要串联；缺证保持待处理。",
      completion: "由目标用户独立导入、检查和交付；改变输入重跑，记录帮助、失败、超时与恢复，不只统计 PASS。",
      reuse: "记录第二项目的格式、规则和配置差异；同一版本按说明独立运行。",
    },
  },
  {
    id: "annotation-rework", title: "人工复核标注与返修", tag: "可操作子任务",
    buyer: "数据交付负责人 / 视觉方案商技术负责人", user: "标注复核工程师与返修人员",
    trigger: "一批标注需要复核，发现疑似偏移、类别争议或几何问题，希望把返修意见与新版本对上。",
    outcome: "定位到图片和框的返修单、追加修订记录、复核依据，以及必要的批次重检。",
    inputs: ["授权图片、已有框和本次标注规范", "返修负责人及有资格判断标注的复核人", "原版本与要比较的修订版本"],
    limitations: ["现有几何检查不能独立判断框是否准确覆盖真实缺陷；标注语义需要人工复核。", "当前工作簿主要支持矩形框编辑；多人盲审仲裁、自动分割和大规模标注生产尚未验证。", "像素工单关闭只绑定较新的标注修订，不触发批次 Child；需另行冻结快照并检查。", "上传快照的本地 PNG 标注合同往返已通过服务层测试；不代表 CVAT/FiftyOne 服务器连接，也不自动回写工作簿框或创建 CAPA Child。"],
    steps: [
      { title: "约定复核标准", person: "数据负责人", detail: "说明对象类别、框选规范、允许的偏差及争议处理人，保留未明确的要求。", output: "复核任务和责任边界", href: "/pilot", action: "约定标注试点" },
      { title: "查看图片与标注", person: "复核工程师", detail: "在工作簿逐项检查图像和框；用测量辅助复核，缺陷语义仍由专业人员判断。", output: "定位到样本与修订的疑点", href: "/workspace", action: "打开标注工作簿" },
      { title: "返修并留下版本", person: "返修人员", detail: "在框上签发像素工单，按要求修订并保存；修订保留原图与追加版本。", output: "框坐标、说明、负责人和修订记录", href: "/capa?layer=pixel", action: "查看像素返修工单" },
      { title: "复核返修并重检", person: "复核工程师", detail: "像素问题关闭需绑定新标注修订；批次验收另需冻结新快照并重新执行检查。", output: "返修复核依据与批次重检结果", href: "/workspace", action: "返回工作簿复核" },
    ],
    proof: {
      value: "观察每批标注复核工时、返修往返和复核通过情况；在第二批标注继续使用。",
      innovation: "图像与标注事实先由工具提供，Agent 依据缺口组织处置；Finding 消失仍需责任关闭条件，不宣称自动语义标注。",
      technology: "检查追加修订、并发版本冲突、工单绑定与新快照重检；原图保留，具名人员接受返修。",
      completion: "复核人能找到图片、选择框、签发问题并检查新修订；记录作者代操作、失败与恢复。",
      reuse: "相同工具适配第二种标注任务时，记录标签规范、导入格式和配置变化。",
    },
  },
  {
    id: "dataset-reuse", title: "维护下一批数据", tag: "持续使用验证",
    buyer: "视觉团队的数据负责人", user: "数据维护工程师",
    trigger: "第一批交付后又收到新数据，需要沿用已有规范检查新批次并保留版本与责任。",
    outcome: "新批次的独立检查结果，以及复用原流程所需的配置与工时记录。",
    inputs: ["第二批未见数据及授权范围", "固定软件版本、规则版本，并重新核对新快照的实际合同内容与摘要", "新增样本、规范变化和第二项目的适配记录"],
    limitations: ["当前有批次与快照基础，不代表已实现无人值守持续监控或完整数据资产平台。", "冻结包含当前项目全部资产；旧项目追加上传得到累计快照，单独验证第二批需新建独立项目。", "相同软件版本不代表生成了相同验收合同，必须核对实际合同内容与摘要。", "跨项目推广成本、团队权限和多机部署需要独立实测。"],
    steps: [
      { title: "记录复用条件", person: "数据负责人", detail: "确认第一批和第二批的差异，固定软件与规则版本，说明允许调整的配置。", output: "第二项目的复用约束", href: "/pilot", action: "约定复用试点" },
      { title: "导入新的批次", person: "数据工程师", detail: "单独验证新批次时先新建独立项目再导入；若追加到原项目，按累计项目快照记录，不能视为仅第二批。", output: "明确独立或累计范围的输入清单", href: "/workspace", action: "进入数据工作簿" },
      { title: "执行同类任务", person: "数据工程师", detail: "按已有流程运行新任务，保留失败、帮助和配置变更，避免沿用旧 PASS。", output: "新任务结果与操作记录", href: "/command-center", action: "查看任务工作台" },
      { title: "核对复用成本", person: "项目负责人", detail: "比较实际配置、开发、培训和支持工时；独立完成并愿意继续用，才形成复用证据。", output: "版本关系与适配成本记录", href: "/lineage", action: "查看版本记录" },
    ],
    proof: {
      value: "用第二项目接入成本和第二批独立使用记录验证持续价值。",
      innovation: "只对新批次实际出现的缺证或冲突补充工作，新事实使旧批准失效，所有结果绑定本次任务。",
      technology: "软件、规则、输入和权限版本可核对；不同客户的数据、真值与适用范围分别授权。",
      completion: "同一用户换批次和另一用户换环境分别实跑，记录学习、操作成本、失败与配置变化。",
      reuse: "区分同格式新批次、跨格式适配与跨环境部署，不合并为通用成功率。",
    },
  },
];

export function findBusinessTask(id: string | null | undefined): BusinessTask | undefined {
  return businessTasks.find((task) => task.id === id);
}

export function businessTaskUrl(id: string, route: "/start" | "/pilot" | "/workspace"): string {
  if (!findBusinessTask(id)) throw new Error("未知的业务任务。");
  return `${route}?purpose=${encodeURIComponent(id)}`;
}
