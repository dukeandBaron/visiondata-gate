import { findBusinessTask, type BusinessTaskId } from "./businessTasks.ts";

export const pilotMetrics = [
  { id: "independent_completion", name: "目标用户独立完成率", unit: "独立完成任务数/全部纳入任务数", definition: "目标用户在约定范围内无需开发者代操作完成检查与交接；正确阻断且问题单完整也可完成审查任务，但不代表整改完成或生产放行。失败、超时和需要帮助的任务必须纳入分母。", evidence: "事前约定的任务清单、帮助记录、实际交付物及独立观察者的完成判定。", tier: "任务" },
  { id: "annotation_rework_acceptance", name: "标注返修独立复核通过率", unit: "独立复核通过的返修样本/全部送审返修样本", definition: "按固定标注规范复核返修结果，重复送审轮次另记；像素工单关闭和几何检查通过不能替代语义正确性复核。", evidence: "冻结标注规范、前后修订、独立复核记录和争议处置；批次检查结果单独统计。", tier: "标注" },
  { id: "evidence_time", name: "复验材料准备时长", unit: "分钟/次交付", definition: "从约定资料齐备到复验包完成的时间；同时记录等待与人工整理时间。", evidence: "同类项目的起止记录、资料清单与交付包。", tier: "流程" },
  { id: "review_labor", name: "人工有效工作时长", unit: "人时/次交付", definition: "参与者实际整理、核对、返修与复验的工作时长之和，包含失败处理、开发者帮助与额外复核；等待单列，不能用页面停留时间替代。", evidence: "人工工时记录；两种流程采用相同任务范围。", tier: "流程" },
  { id: "rework_rounds", name: "整改往返次数", unit: "轮/次交付", definition: "观察窗内全部整改往返，包括未成功和仍未关闭的轮次。", evidence: "每轮问题、负责人、变更和复验记录。", tier: "流程" },
  { id: "inspection_ng", name: "检测系统 NG 报警率", unit: "报警件/检测件", definition: "系统判为 NG 的工件占比。下降可能源于误报减少，也可能源于漏检增加。", evidence: "同工位、产品、时间窗的判定日志和实际检测分母。", tier: "检测" },
  { id: "miss_rate", name: "缺陷件漏检率", unit: "漏判合格的缺陷件/全部真实缺陷件", definition: "由独立复核确认的缺陷件中，被检测系统误判合格的比例。", evidence: "冻结测试集、检测结果、独立实物或双人裁决。", tier: "检测" },
  { id: "false_reject", name: "良品误剔率", unit: "误判不合格的良品/全部真实良品", definition: "由独立复核确认的良品中，被检测系统误判不合格的比例。", evidence: "同一冻结测试集与独立真值，不能只审查 NG 件。", tier: "检测" },
  { id: "physical_defect", name: "真实产品缺陷率", unit: "真实缺陷件/独立检验件", definition: "按固定抽检协议确认的实际缺陷比例；数据整改通过不能推断工艺质量改善。", evidence: "独立抽检、批次与工况；额外记录设备、工艺和人员变更。", tier: "生产" },
  { id: "reuse_effort", name: "第二项目接入成本", unit: "人时/项目", definition: "相同软件版本迁移到第二项目所需的配置、开发、部署、培训和支持工作量；同格式新批次与跨格式项目分别记录。", evidence: "软件版本、配置差异、代码变更和支持工时；额外采购及计算费用单列。", tier: "复制" },
] as const;

export type PilotMetricId = (typeof pilotMetrics)[number]["id"];

export const pilotFields = [
  { key: "projectAlias", label: "项目代号", placeholder: "使用内部代号即可", max: 120 },
  { key: "buyerRole", label: "预算负责人角色", placeholder: "如：视觉方案商交付负责人", max: 120 },
  { key: "operatorRole", label: "实际使用者角色", placeholder: "如：应用工程师与质量工程师", max: 120 },
  { key: "workcell", label: "项目、批次与产品范围", placeholder: "限定一次交付：如产品族 A 的标注批次 / 工位 B 的换型复验", max: 240 },
  { key: "problem", label: "最近一次实际问题", placeholder: "描述发生了什么、原来如何处理，未确认的原因也请保留。", max: 2000 },
  { key: "dataScope", label: "授权输入范围", placeholder: "图像、标注、划分、配置版本等；填写范围说明，不填写凭据或客户原图。", max: 2000 },
  { key: "observationWindow", label: "观察周期与纳入规则", placeholder: "起止日期、哪些交付/批次纳入，避免事后只挑成功案例。", max: 1000 },
  { key: "baselineMethod", label: "对照与独立复核方法", placeholder: "现有流程与新流程如何比较？检测指标由谁独立裁决？", max: 2000 },
  { key: "acceptanceCriteria", label: "待双方确认的验收条件", placeholder: "约定交付物、负责人、指标要求、成本范围和未通过时的处理。", max: 2000 },
] as const;

export type PilotField = (typeof pilotFields)[number]["key"];
export type PilotDraft = Record<PilotField, string> & { metricIds: PilotMetricId[]; businessTaskId: BusinessTaskId };

export function emptyPilotDraft(): PilotDraft {
  return { projectAlias: "", buyerRole: "", operatorRole: "", workcell: "", problem: "", dataScope: "", observationWindow: "", baselineMethod: "", acceptanceCriteria: "", businessTaskId: "dataset-acceptance", metricIds: ["independent_completion", "review_labor", "rework_rounds", "reuse_effort"] };
}

function checkedDraft(input: unknown): PilotDraft {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("试点范围格式不正确。");
  const source = input as Record<string, unknown>;
  const draft = emptyPilotDraft();
  for (const field of pilotFields) {
    const value = source[field.key];
    if (typeof value !== "string" || !value.trim()) throw new Error(`请填写${field.label}。`);
    if (value.length > field.max) throw new Error(`${field.label}超出长度限制。`);
    draft[field.key] = value.trim();
  }
  const ids = source.metricIds;
  if (!Array.isArray(ids) || !ids.length || ids.length > pilotMetrics.length || ids.some((id) => !pilotMetrics.some((metric) => metric.id === id)) || new Set(ids).size !== ids.length) {
    throw new Error("请选择至少一项有效且不重复的观察指标。");
  }
  draft.metricIds = [...ids] as PilotMetricId[];
  const task = typeof source.businessTaskId === "string" ? findBusinessTask(source.businessTaskId) : undefined;
  if (!task) throw new Error("请选择有效的业务任务。");
  draft.businessTaskId = task.id;
  return draft;
}

export function buildPilotPlan(input: unknown) {
  const draft = checkedDraft(input);
  const task = findBusinessTask(draft.businessTaskId)!;
  return {
    schema_version: "industrial-delivery.pilot-plan.v2",
    status: "DRAFT_NOT_APPROVED",
    customer_validation: "NOT_MEASURED",
    production_release_allowed: false,
    machine_write_permitted: false,
    scope: draft,
    business_task: { id: task.id, title: task.title, expected_output: task.outcome, limitations: [...task.limitations] },
    deliverables: task.steps.map((step) => step.output),
    measurements: pilotMetrics.filter((metric) => draft.metricIds.includes(metric.id)).map((metric) => ({ ...metric, status: "NOT_MEASURED", baseline: null, after: null, evidence_ref: null })),
    boundary: "范围书仅供试点讨论，不是客户签署、测量结果、合作承诺或生产批准。检测系统 NG 报警率、漏检率、良品误剔率和真实产品缺陷率分别统计。",
  };
}

export function parsePilotPlan(text: string): PilotDraft {
  if (text.length > 50000) throw new Error("仅支持 50 KB 以内的试点范围书。");
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object") throw new Error("试点范围书格式不正确。");
  const plan = value as Record<string, unknown>;
  const legacy = plan.schema_version === "industrial-delivery.pilot-plan.v1";
  if ((!legacy && plan.schema_version !== "industrial-delivery.pilot-plan.v2") || plan.status !== "DRAFT_NOT_APPROVED" || plan.customer_validation !== "NOT_MEASURED" || plan.production_release_allowed !== false || plan.machine_write_permitted !== false) {
    throw new Error("只接受未批准、未测量的试点草稿；此页面不能导入验收或授权回执。");
  }
  if (!plan.scope || typeof plan.scope !== "object" || Array.isArray(plan.scope)) throw new Error("试点范围格式不正确。");
  const scope = plan.scope as Record<string, unknown>;
  const draft = checkedDraft(legacy && scope.businessTaskId === undefined ? { ...scope, businessTaskId: "dataset-acceptance" } : scope);
  if (!legacy && (!plan.business_task || typeof plan.business_task !== "object" || (plan.business_task as Record<string, unknown>).id !== draft.businessTaskId)) {
    throw new Error("范围书中的业务任务绑定不一致。");
  }
  const expected = buildPilotPlan(draft).measurements;
  if (!Array.isArray(plan.measurements) || plan.measurements.length !== expected.length || plan.measurements.some((row, i) => !row || row.id !== expected[i]?.id || row.status !== "NOT_MEASURED" || row.baseline !== null || row.after !== null || row.evidence_ref !== null)) {
    throw new Error("范围书不得携带测量结论；请在真实业务流程中另行核验结果。");
  }
  return draft;
}
