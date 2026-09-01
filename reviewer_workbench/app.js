"use strict";

const SNAPSHOT_ENDPOINT = "/api/reviewer/snapshot";
const API_SNAPSHOT_SCHEMA = "visiondata-gate.reviewer-workbench.v1";
const INTERNAL_SNAPSHOT_SCHEMA = "visiondata-gate.reviewer-ui.v1";
const IMAGE_ENDPOINTS = {
  before: "/api/reviewer/assets/before",
  after: "/api/reviewer/assets/after",
};

const FALLBACK_SNAPSHOT = {
  schema_version: INTERNAL_SNAPSHOT_SCHEMA,
  generated_at: "NOT_EXPOSED_IN_FALLBACK",
  audit_anchor: "NOT_EXPOSED_IN_FALLBACK",
  approver: "NOT_SUPPLIED",
  production: false,
  external_model: {
    base_url: "https://gw.opentoken.io",
    mode: "off",
    key_configured: false,
    connection_status: "NOT_CONFIGURED",
  },
  visual: {
    label: "Synthetic-v3 合成工程证据",
    evidence_class: "synthetic_injected_truth",
    boundary: "Embedded SVG fallback is not an evidence image or factory result.",
    observed: "1.8585",
    minimum: "18",
    algorithm: "Laplacian sharpness",
    result: "LOW_SHARPNESS",
    initial_decision: "RECAPTURE",
    recheck_decision: "NOT_CLAIMED_IN_FALLBACK",
    before_url: IMAGE_ENDPOINTS.before,
    after_url: IMAGE_ENDPOINTS.after,
    sample_id: "q-blur",
    finding_code: "LOW_SHARPNESS",
    mean_luma: "NOT_EXPOSED_IN_FALLBACK",
    before_sha256: "NOT_EXPOSED_IN_FALLBACK",
    after_sha256: "NOT_EXPOSED_IN_FALLBACK",
  },
  cases: [
    {
      id: "omni-rc3-capa",
      short_label: "RC3 · CAPA _05",
      title: "Omni RC3 · CAPA 复验案件",
      status: "HOLD",
      lifecycle: "TRANSFERRED_TO_INVESTIGATION",
      path: "omni_rc3/capa_05",
      boundary:
        "本地授权 RC3 工程证据。49→33 findings；6 条责任项关闭、43 条仍打开。不是生产恢复、工厂验收或官方提交结果。",
      phase_progress: "3/4 · HOLD",
      findings: [
        {
          id: "rc3-parent-findings",
          code: "PARENT",
          title: "Parent findings",
          subtitle: "父 Run 聚合证据",
          value: "49",
          status: "RECAPTURE",
          summary: "父 Run 在当前冻结 RC3 证据中记录 49 个 findings。",
          scope: "aggregate evidence",
          disposition: "child verification required",
        },
        {
          id: "rc3-child-findings",
          code: "CHILD",
          title: "Child findings",
          subtitle: "独立 Child Run 聚合证据",
          value: "33",
          status: "RECAPTURE",
          summary: "受控派生后由独立 Child Run 复验，记录 33 个 findings。",
          scope: "aggregate evidence",
          disposition: "not a release pass",
        },
        {
          id: "rc3-closed-items",
          code: "CLOSED",
          title: "已关闭责任项",
          subtitle: "满足关闭条件",
          value: "6",
          status: "CLOSED",
          summary: "本次复验中只有 6 条责任项满足关闭条件。",
          scope: "responsibility queue",
          disposition: "closed",
        },
        {
          id: "rc3-open-items",
          code: "OPEN",
          title: "仍打开责任项",
          subtitle: "继续人工调查",
          value: "43",
          status: "HOLD",
          summary: "43 条责任项仍然打开，因此维持 HOLD 并转入人工调查。",
          scope: "responsibility queue",
          disposition: "TRANSFERRED_TO_INVESTIGATION",
        },
      ],
      orders: {
        title: "RC3 责任队列",
        status: "HOLD",
        description:
          "当前授权候选池没有观察到可发布方案。责任项没有全部关闭，Reviewer Workbench 不提供放行按钮。",
        metrics: [
          { label: "Parent findings", value: "49" },
          { label: "Child findings", value: "33" },
          { label: "Closed", value: "6" },
          { label: "Open", value: "43" },
        ],
        boundary: "production=false · release remains HOLD",
      },
      lineage: {
        edge_label: "authorized derived run",
        nodes: [
          {
            id: "parent",
            role: "PARENT RUN",
            title: "Parent Case",
            value: "49 findings",
            status: "RECAPTURE",
            detail: "父 Run 保存原始证据边界，并要求同合同的独立 Child Run 复验。",
            available: true,
          },
          {
            id: "capa",
            role: "HUMAN CAPA",
            title: "Named-human approval",
            value: "49 selected orders",
            status: "NAMED_HUMAN_ONLY",
            detail: "批准权属于具名人类；Parent 未被覆盖。",
            available: true,
          },
          {
            id: "derived",
            role: "PRIVATE DERIVED",
            title: "Derived version",
            value: "180 images / 60 masks",
            status: "private=true",
            detail: "只在私有派生版本执行；父来源保持不变。",
            available: true,
          },
          {
            id: "child",
            role: "CHILD RUN",
            title: "Child Case",
            value: "33 findings",
            status: "RECAPTURE",
            detail: "Child Run 复验后仍有 43 条责任项打开；案件转入人工调查，生产放行为 false。",
            available: true,
          },
        ],
      },
      phases: [
        { label: "父 Run 取证", detail: "49 findings", status: "complete" },
        { label: "受控 CAPA", detail: "仅对派生版本执行", status: "complete" },
        { label: "独立 Child 复验", detail: "33 findings", status: "complete" },
        { label: "生产发布门禁", detail: "6 closed / 43 open", status: "hold" },
      ],
      traces: [
        {
          code: "01",
          title: "Governed outcome receipt",
          subtitle: "Parent / Child 聚合结果",
          status: "HOLD",
          payload:
            "parent_findings=49\nchild_findings=33\nresponsibility_closed=6\nresponsibility_open=43\nproduction=false",
        },
        {
          code: "02",
          title: "Fail-closed policy judge",
          subtitle: "未清责任项阻断放行",
          status: "HOLD",
          payload:
            "case_state=TRANSFERRED_TO_INVESTIGATION\nrelease_state=HOLD\nproduction_decision_authority=human_only",
        },
        {
          code: "03",
          title: "Evidence scope",
          subtitle: "本地工程证据边界",
          status: "READONLY",
          payload:
            "scope=LOCAL_AUTHORIZED_RC3_EVIDENCE\nfactory_acceptance=false\nofficial_submission_result=NOT_EVALUATED",
        },
      ],
    },
    {
      id: "omni-rc2-reviewer",
      short_label: "RC2 · Reviewer Demo",
      title: "Omni-180-v1 · RC2 冻结 Pilot",
      status: "RECAPTURE",
      lifecycle: "LOCAL_CONTRACT_VALIDATED",
      path: "omni_180_v1/rc2",
      boundary:
        "冻结公开 Pilot：180 张样本、45 findings / 45 工单、1 次 replan、3 个 Workers。不能替代 RC3，也不是生产部署。",
      phase_progress: "3/4 · RECAPTURE",
      findings: [
        {
          id: "rc2-denominator",
          code: "GATE",
          title: "冻结 Gate denominator",
          subtitle: "Omni-180-v1",
          value: "180",
          status: "FIXED",
          summary: "RC2 Reviewer Demo 使用冻结的 180 张公开样本。",
          scope: "frozen public pilot",
          disposition: "read-only evaluation",
        },
        {
          id: "rc2-findings",
          code: "FINDINGS",
          title: "结构化 findings",
          subtitle: "聚合数量",
          value: "45",
          status: "RECAPTURE",
          summary: "固定 Gate 交付 45 个 findings；fallback 不虚构单条类别或测量值。",
          scope: "aggregate evidence",
          disposition: "45 work orders",
        },
        {
          id: "rc2-replan",
          code: "REPLAN",
          title: "证据触发重规划",
          subtitle: "受控执行回执",
          value: "1×",
          status: "COMPLETE",
          summary: "冻结 RC2 证据记录 1 次 replan，并调度 3 个 Workers。",
          scope: "governed trace",
          disposition: "3 workers",
        },
      ],
      orders: {
        title: "RC2 工单摘要",
        status: "RECAPTURE",
        description:
          "45 个 findings 映射为 45 张结构化工单。fallback 只展示已冻结的聚合数量，不构造工单坐标、缺陷类别或效果指标。",
        metrics: [
          { label: "Frozen images", value: "180" },
          { label: "Findings", value: "45" },
          { label: "Work orders", value: "45" },
          { label: "Replan / Workers", value: "1 / 3" },
        ],
        boundary: "decision=RECAPTURE · production=false",
      },
      lineage: {
        edge_label: "no child bundled",
        nodes: [
          {
            id: "parent",
            role: "FROZEN PILOT",
            title: "RC2 Parent",
            value: "180 images",
            status: "RECAPTURE",
            detail: "冻结 RC2 Pilot 交付 45 findings 与 45 工单。",
            available: true,
          },
          {
            id: "child",
            role: "CHILD RUN",
            title: "Not bundled",
            value: "NOT_AVAILABLE",
            status: "NOT_AVAILABLE",
            detail: "RC2 fallback 不把 RC3 的 Child 结果拼接进该案件。",
            available: false,
          },
        ],
      },
      phases: [
        { label: "冻结样本取证", detail: "180 images", status: "complete" },
        { label: "证据触发重规划", detail: "1 replan", status: "complete" },
        { label: "Workers 与工单", detail: "3 workers / 45 orders", status: "complete" },
        { label: "发布门禁", detail: "RECAPTURE", status: "hold" },
      ],
      traces: [
        {
          code: "01",
          title: "Frozen Gate receipt",
          subtitle: "Omni-180-v1",
          status: "COMPLETE",
          payload:
            "fixed_image_denominator=180\nfinding_count=45\nwork_order_count=45\ndecision=RECAPTURE",
        },
        {
          code: "02",
          title: "Planner dispatch receipt",
          subtitle: "结构化摘要，非思维链",
          status: "COMPLETE",
          payload: "replan_count=1\ndynamic_worker_count=3\nproduction=false",
        },
        {
          code: "03",
          title: "Synthetic-v3 optical receipt",
          subtitle: "独立合成 fixture",
          status: "RECAPTURE",
          payload:
            "namespace=Synthetic-v3\nalgorithm=laplacian_sharpness\nobserved=1.8585\nthreshold=18\nreal_factory_image=false",
        },
      ],
    },
  ],
};

const state = {
  snapshot: FALLBACK_SNAPSHOT,
  source: "fallback",
  selectedCaseId: "omni-rc3-capa",
  selectedFindingId: "rc3-open-items",
  selectedLineageId: "child",
  evidenceView: "findings",
  imageMode: "before",
  mobilePanel: "workspace",
};

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeText(value, fallback = "NOT_EXPOSED") {
  if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") return fallback;
  const text = String(value).trim();
  return text ? text.slice(0, 4000) : fallback;
}

function safeProviderOrigin(value) {
  try {
    const parsed = new URL(String(value));
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") throw new Error("unsupported protocol");
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return "https://gw.opentoken.io";
  }
}

function normalizeProvider(value) {
  const source = value && typeof value === "object" ? value : {};
  const keyConfigured = source.key_configured === true;
  let connectionStatus = safeText(source.connection_status, "NOT_CONFIGURED").toUpperCase();
  if (!keyConfigured) connectionStatus = "NOT_CONFIGURED";
  return {
    base_url: safeProviderOrigin(source.base_url || "https://gw.opentoken.io"),
    mode: safeText(source.mode, "openai-compatible"),
    key_configured: keyConfigured,
    connection_status: connectionStatus,
  };
}

function isValidCase(item) {
  return Boolean(
    item &&
      typeof item === "object" &&
      typeof item.id === "string" &&
      Array.isArray(item.findings) &&
      item.orders &&
      Array.isArray(item.orders.metrics) &&
      item.lineage &&
      Array.isArray(item.lineage.nodes) &&
      Array.isArray(item.phases) &&
      Array.isArray(item.traces),
  );
}

function phaseClass(status) {
  const value = safeText(status, "NOT_EXPOSED").toUpperCase();
  if (value.includes("HOLD") || value.includes("BLOCK") || value.includes("RECAPTURE")) return "hold";
  if (value.startsWith("COMPLETED") || value === "PASS") return "complete";
  return "pending";
}

function receiptLines(entries) {
  return entries.map(([key, value]) => `${key}=${safeText(value)}`).join("\n");
}

function adaptReviewerWorkbenchSnapshot(payload) {
  const caseInfo = payload.case;
  const pilot = payload.public_pilot;
  const runtime = payload.runtime;
  const visual = payload.synthetic_visual;
  const integrity = payload.snapshot_integrity;
  if (
    !caseInfo ||
    !caseInfo.parent ||
    !caseInfo.capa ||
    !caseInfo.derived ||
    !caseInfo.child ||
    !pilot ||
    !runtime ||
    !visual ||
    !visual.measurement ||
    !integrity ||
    !Array.isArray(payload.phases)
  ) {
    throw new Error("reviewer workbench snapshot is incomplete");
  }

  const rc3 = {
    id: safeText(caseInfo.case_id),
    short_label: safeText(caseInfo.display_name),
    title: safeText(caseInfo.display_name),
    status: safeText(caseInfo.status),
    lifecycle: safeText(caseInfo.child.status),
    path: `case/${safeText(caseInfo.case_id)}`,
    boundary: safeText(caseInfo.boundary),
    phase_progress: `${payload.phases.length} phases · ${safeText(caseInfo.status)}`,
    findings: [
      {
        id: "api-parent-findings",
        code: "PARENT",
        title: "Parent findings",
        subtitle: safeText(caseInfo.parent.version),
        value: safeText(caseInfo.parent.findings),
        status: safeText(caseInfo.parent.decision),
        summary: `API snapshot 的 Parent ${safeText(caseInfo.parent.version)} 记录 ${safeText(caseInfo.parent.findings)} 个 findings。`,
        scope: safeText(caseInfo.evidence_class),
        disposition: "child verification required",
      },
      {
        id: "api-child-findings",
        code: "CHILD",
        title: "Child findings",
        subtitle: safeText(caseInfo.child.version),
        value: safeText(caseInfo.child.findings),
        status: safeText(caseInfo.child.status),
        summary: `API snapshot 的 Child ${safeText(caseInfo.child.version)} 记录 ${safeText(caseInfo.child.findings)} 个 findings。`,
        scope: safeText(caseInfo.evidence_class),
        disposition: safeText(caseInfo.child.status),
      },
      {
        id: "api-verified-closed",
        code: "CLOSED",
        title: "已验证关闭责任项",
        subtitle: "verified_closed",
        value: safeText(caseInfo.child.verified_closed),
        status: "VERIFIED_CLOSED",
        summary: `API snapshot 报告 ${safeText(caseInfo.child.verified_closed)} 条责任项已验证关闭。`,
        scope: safeText(caseInfo.evidence_class),
        disposition: "verified_closed",
      },
      {
        id: "api-open-responsibilities",
        code: "OPEN",
        title: "仍打开责任项",
        subtitle: safeText(caseInfo.child.status),
        value: safeText(caseInfo.child.open_responsibilities),
        status: safeText(caseInfo.status),
        summary: `API snapshot 报告 ${safeText(caseInfo.child.open_responsibilities)} 条责任项仍打开。`,
        scope: safeText(caseInfo.evidence_class),
        disposition: safeText(caseInfo.child.status),
      },
    ],
    orders: {
      title: "RC3 责任队列摘要",
      status: safeText(caseInfo.status),
      description: safeText(caseInfo.boundary),
      metrics: [
        { label: "Parent findings", value: safeText(caseInfo.parent.findings) },
        { label: "Child findings", value: safeText(caseInfo.child.findings) },
        { label: "Verified closed", value: safeText(caseInfo.child.verified_closed) },
        { label: "Open", value: safeText(caseInfo.child.open_responsibilities) },
      ],
      boundary: `production_release_allowed=${String(caseInfo.production_release_allowed === true)}`,
    },
    lineage: {
      edge_label: "API snapshot · CAPA derived run",
      nodes: [
        {
          id: "parent",
          role: `PARENT ${safeText(caseInfo.parent.version)}`,
          title: "Parent Case",
          value: `${safeText(caseInfo.parent.findings)} findings`,
          status: safeText(caseInfo.parent.decision),
          detail: `Parent decision=${safeText(caseInfo.parent.decision)}；parent_mutated=${String(caseInfo.capa.parent_mutated === true)}。`,
          available: true,
        },
        {
          id: "capa",
          role: "HUMAN CAPA",
          title: "Named-human approval",
          value: `${safeText(caseInfo.capa.selected_work_orders)} selected orders`,
          status: safeText(caseInfo.capa.approval_authority),
          detail: `approval_authority=${safeText(caseInfo.capa.approval_authority)}；selected_work_orders=${safeText(caseInfo.capa.selected_work_orders)}；parent_mutated=${String(caseInfo.capa.parent_mutated === true)}。`,
          available: true,
        },
        {
          id: "derived",
          role: "PRIVATE DERIVED",
          title: "Derived version",
          value: `${safeText(caseInfo.derived.images)} images / ${safeText(caseInfo.derived.masks)} masks`,
          status: `private=${String(caseInfo.derived.private === true)}`,
          detail: `images=${safeText(caseInfo.derived.images)}；masks=${safeText(caseInfo.derived.masks)}；private=${String(caseInfo.derived.private === true)}。`,
          available: true,
        },
        {
          id: "child",
          role: `CHILD ${safeText(caseInfo.child.version)}`,
          title: "Child Case",
          value: `${safeText(caseInfo.child.findings)} findings`,
          status: safeText(caseInfo.child.status),
          detail: `verified_closed=${safeText(caseInfo.child.verified_closed)}；open_responsibilities=${safeText(caseInfo.child.open_responsibilities)}；production_release_allowed=${String(caseInfo.production_release_allowed === true)}。`,
          available: true,
        },
      ],
    },
    phases: payload.phases.map((item) => ({
      label: safeText(item.label),
      detail: safeText(item.status),
      status: phaseClass(item.status),
    })),
    traces: [
      {
        code: "01",
        title: "Parent / Child evidence receipt",
        subtitle: safeText(caseInfo.evidence_class),
        status: safeText(caseInfo.status),
        payload: receiptLines([
          ["parent_findings", caseInfo.parent.findings],
          ["child_findings", caseInfo.child.findings],
          ["verified_closed", caseInfo.child.verified_closed],
          ["open_responsibilities", caseInfo.child.open_responsibilities],
          ["production_release_allowed", caseInfo.production_release_allowed === true],
        ]),
      },
      {
        code: "02",
        title: "Human CAPA boundary",
        subtitle: safeText(caseInfo.capa.approval_authority),
        status: safeText(caseInfo.child.status),
        payload: receiptLines([
          ["selected_work_orders", caseInfo.capa.selected_work_orders],
          ["approval_authority", caseInfo.capa.approval_authority],
          ["parent_mutated", caseInfo.capa.parent_mutated === true],
        ]),
      },
      {
        code: "03",
        title: "Governed runtime receipt",
        subtitle: "API runtime projection",
        status: safeText(runtime.tool_access),
        payload: receiptLines([
          ["planner_mode", runtime.planner_mode],
          ["tool_access", runtime.tool_access],
          ["chain_of_thought_exposed", runtime.chain_of_thought_exposed === true],
          ["signature", runtime.signature],
        ]),
      },
    ],
  };

  const publicPilot = {
    id: safeText(pilot.release_id),
    short_label: `${safeText(pilot.evidence_namespace)} · Public Pilot`,
    title: `${safeText(pilot.evidence_namespace)} · 冻结公开 Pilot`,
    status: safeText(pilot.decision),
    lifecycle: safeText(pilot.evidence_class),
    path: `public_pilot/${safeText(pilot.release_id)}`,
    boundary: safeText(pilot.claim_boundary),
    phase_progress: `Gate · ${safeText(pilot.decision)}`,
    findings: [
      {
        id: "api-pilot-denominator",
        code: "GATE",
        title: "冻结 Gate denominator",
        subtitle: safeText(pilot.evidence_namespace),
        value: safeText(pilot.fixed_image_denominator),
        status: "FIXED",
        summary: `API public_pilot 固定样本分母为 ${safeText(pilot.fixed_image_denominator)}。`,
        scope: safeText(pilot.evidence_class),
        disposition: safeText(pilot.decision),
      },
      {
        id: "api-pilot-findings",
        code: "FINDINGS",
        title: "结构化 findings",
        subtitle: "finding_count",
        value: safeText(pilot.finding_count),
        status: safeText(pilot.decision),
        summary: `API public_pilot 报告 ${safeText(pilot.finding_count)} 个 findings。`,
        scope: safeText(pilot.evidence_class),
        disposition: `${safeText(pilot.work_order_count)} work orders`,
      },
      {
        id: "api-pilot-replan",
        code: "REPLAN",
        title: "证据触发重规划",
        subtitle: "governed dispatch",
        value: safeText(pilot.replan_count),
        status: "COMPLETED",
        summary: `API public_pilot 报告 ${safeText(pilot.replan_count)} 次 replan 和 ${safeText(pilot.dynamic_worker_count)} 个 dynamic Workers。`,
        scope: "public_pilot.dynamic_tasks",
        disposition: `${safeText(pilot.dynamic_worker_count)} workers`,
      },
    ],
    orders: {
      title: "Public Pilot 工单摘要",
      status: safeText(pilot.decision),
      description: safeText(pilot.claim_boundary),
      metrics: [
        { label: "Frozen images", value: safeText(pilot.fixed_image_denominator) },
        { label: "Findings", value: safeText(pilot.finding_count) },
        { label: "Work orders", value: safeText(pilot.work_order_count) },
        { label: "Replan / Workers", value: `${safeText(pilot.replan_count)} / ${safeText(pilot.dynamic_worker_count)}` },
      ],
      boundary: `actual_model_call_count=${safeText(pilot.actual_model_call_count)}`,
    },
    lineage: {
      edge_label: "no child in public_pilot contract",
      nodes: [
        {
          id: "parent",
          role: "PUBLIC PILOT",
          title: safeText(pilot.evidence_namespace),
          value: `${safeText(pilot.fixed_image_denominator)} images`,
          status: safeText(pilot.decision),
          detail: safeText(pilot.claim_boundary),
          available: true,
        },
        {
          id: "child",
          role: "CHILD RUN",
          title: "Not in contract",
          value: "NOT_EXPOSED",
          status: "NOT_EXPOSED",
          detail: "public_pilot snapshot 未提供 Child Run 字段。",
          available: false,
        },
      ],
    },
    phases: [
      { label: "冻结样本取证", detail: `${safeText(pilot.fixed_image_denominator)} images`, status: "complete" },
      { label: "证据触发重规划", detail: `${safeText(pilot.replan_count)} replan`, status: "complete" },
      { label: "Workers 与工单", detail: `${safeText(pilot.dynamic_worker_count)} workers / ${safeText(pilot.work_order_count)} orders`, status: "complete" },
      { label: "发布门禁", detail: safeText(pilot.decision), status: phaseClass(pilot.decision) },
    ],
    traces: [
      {
        code: "01",
        title: "Public Pilot Gate receipt",
        subtitle: safeText(pilot.evidence_namespace),
        status: safeText(pilot.decision),
        payload: receiptLines([
          ["fixed_image_denominator", pilot.fixed_image_denominator],
          ["finding_count", pilot.finding_count],
          ["work_order_count", pilot.work_order_count],
          ["decision", pilot.decision],
        ]),
      },
      {
        code: "02",
        title: "Planner dispatch receipt",
        subtitle: "API dynamic task aggregate",
        status: "COMPLETED",
        payload: receiptLines([
          ["replan_count", pilot.replan_count],
          ["dynamic_worker_count", pilot.dynamic_worker_count],
          ["dynamic_task_count", Array.isArray(pilot.dynamic_tasks) ? pilot.dynamic_tasks.length : "NOT_EXPOSED"],
          ["actual_model_call_count", pilot.actual_model_call_count],
        ]),
      },
      {
        code: "03",
        title: "Tool receipt aggregate",
        subtitle: "read-only public projection",
        status: "READ_ONLY",
        payload: receiptLines([
          ["tool_trace_count", Array.isArray(pilot.tool_trace) ? pilot.tool_trace.length : "NOT_EXPOSED"],
          ["rule_check_count", pilot.rule_check_count],
          ["gate_result_sha256", pilot.gate_result_sha256],
        ]),
      },
    ],
  };

  return {
    schema_version: INTERNAL_SNAPSHOT_SCHEMA,
    generated_at: "NOT_EXPOSED",
    audit_anchor: safeText(integrity.sha256),
    approver: safeText(caseInfo.owner, "NOT_SUPPLIED"),
    production: false,
    external_model: normalizeProvider(payload.external_model),
    visual: {
      label: safeText(visual.label, "Synthetic-v3"),
      evidence_class: safeText(visual.evidence_class),
      boundary: safeText(visual.boundary),
      observed: safeText(visual.measurement.observed),
      minimum: safeText(visual.measurement.minimum),
      algorithm: safeText(visual.measurement.algorithm),
      result: safeText(visual.measurement.result),
      initial_decision: safeText(visual.initial_decision),
      recheck_decision: safeText(visual.recheck_decision),
      before_url: safeText(visual.before && visual.before.url, IMAGE_ENDPOINTS.before),
      after_url: safeText(visual.after && visual.after.url, IMAGE_ENDPOINTS.after),
      sample_id: safeText(visual.sample_id),
      finding_code: safeText(visual.finding_code),
      mean_luma: safeText(visual.measurement.mean_luma),
      before_sha256: safeText(visual.before && visual.before.sha256),
      after_sha256: safeText(visual.after && visual.after.sha256),
    },
    cases: [rc3, publicPilot],
  };
}

function normalizeSnapshot(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("reviewer snapshot is not an object");
  }
  if (payload.schema_version === API_SNAPSHOT_SCHEMA) {
    return adaptReviewerWorkbenchSnapshot(payload);
  }
  if (payload.schema_version !== INTERNAL_SNAPSHOT_SCHEMA || !Array.isArray(payload.cases)) {
    throw new Error("reviewer snapshot schema mismatch");
  }
  if (!payload.cases.length || !payload.cases.every(isValidCase)) {
    throw new Error("reviewer snapshot cases are incomplete");
  }
  return {
    schema_version: INTERNAL_SNAPSHOT_SCHEMA,
    generated_at: safeText(payload.generated_at, "NOT_EXPOSED"),
    audit_anchor: safeText(payload.audit_anchor, "NOT_EXPOSED"),
    approver: safeText(payload.approver, "NOT_SUPPLIED"),
    production: false,
    external_model: normalizeProvider(payload.external_model),
    visual: payload.visual || FALLBACK_SNAPSHOT.visual,
    cases: payload.cases,
  };
}

function getCurrentCase() {
  return (
    state.snapshot.cases.find((item) => item.id === state.selectedCaseId) ||
    state.snapshot.cases[0] ||
    FALLBACK_SNAPSHOT.cases[0]
  );
}

function makeFallbackSvg(kind) {
  const before = kind === "before";
  const accent = before ? "#ff777f" : "#5790ff";
  const title = before ? "BEFORE · SYNTHETIC-v3" : "AFTER SLOT · SYNTHETIC-v3";
  const subtitle = before
    ? "Laplacian 1.8585 &lt; threshold 18"
    : "No PASS metric bundled in fallback";
  const blocks = Array.from({ length: 48 }, (_, index) => {
    const x = 72 + (index % 8) * 104;
    const y = 130 + Math.floor(index / 8) * 67;
    const opacity = before ? 0.23 + ((index * 7) % 8) / 42 : 0.2 + ((index * 5) % 7) / 40;
    return `<rect x="${x}" y="${y}" width="72" height="39" rx="7" fill="#6f8298" opacity="${opacity}"/>`;
  }).join("");
  const blurOpen = before ? '<g filter="url(#soft)">' : "<g>";
  return `
    <svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640">
      <defs>
        <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stop-color="#0d151f"/><stop offset="1" stop-color="#060a10"/>
        </linearGradient>
        <filter id="soft"><feGaussianBlur stdDeviation="3.2"/></filter>
        <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
          <path d="M32 0H0V32" fill="none" stroke="#273648" stroke-width="1" opacity=".48"/>
        </pattern>
      </defs>
      <rect width="960" height="640" fill="url(#bg)"/>
      <rect width="960" height="640" fill="url(#grid)"/>
      ${blurOpen}${blocks}</g>
      <rect x="48" y="102" width="864" height="446" rx="14" fill="none" stroke="${accent}" stroke-width="2" opacity=".7"/>
      <path d="M48 170h864M48 480h864" stroke="${accent}" stroke-width="1" opacity=".25"/>
      <text x="52" y="62" fill="#eaf2fb" font-family="Segoe UI, sans-serif" font-size="25" font-weight="700">${title}</text>
      <text x="52" y="88" fill="#7f90a5" font-family="Cascadia Code, monospace" font-size="13">${subtitle}</text>
      <text x="52" y="590" fill="#5f7187" font-family="Cascadia Code, monospace" font-size="12">embedded visual fallback · not a factory image · not an effect claim</text>
    </svg>`;
}

function toDataUri(svg) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function bindImageFallback(kind) {
  const image = byId(`${kind}Image`);
  const label = byId(`${kind}AssetState`);
  image.dataset.assetSource = "embedded-fallback";
  image.src = toDataUri(makeFallbackSvg(kind));
  label.textContent = "embedded fallback";

  const probe = new Image();
  probe.addEventListener("load", () => {
    image.dataset.assetSource = "api";
    image.src = IMAGE_ENDPOINTS[kind];
    label.textContent = "API asset";
  });
  probe.src = IMAGE_ENDPOINTS[kind];
}

function renderCaseList() {
  const list = byId("caseList");
  byId("caseCount").textContent = String(state.snapshot.cases.length);
  list.innerHTML = state.snapshot.cases
    .map(
      (item) => `
        <button class="case-row ${item.id === state.selectedCaseId ? "is-active" : ""}" type="button" data-case-id="${escapeHtml(item.id)}">
          <svg><use href="#i-case"></use></svg>
          <span class="case-row-copy">
            <strong>${escapeHtml(item.short_label || item.title)}</strong>
            <small>${escapeHtml(item.lifecycle || "LOCAL_EVIDENCE")}</small>
          </span>
          <span class="mini-status">${escapeHtml(item.status)}</span>
        </button>`,
    )
    .join("");
  list.querySelectorAll("[data-case-id]").forEach((button) => {
    button.addEventListener("click", () => selectCase(button.dataset.caseId));
  });
}

function renderHeader(caseData) {
  byId("topCaseTitle").textContent = safeText(caseData.title);
  byId("topCaseAnchor").textContent = `Audit anchor · ${safeText(state.snapshot.audit_anchor)}`;
  byId("approverLabel").textContent = safeText(state.snapshot.approver, "NOT_SUPPLIED");
  byId("workspaceCasePath").textContent = safeText(caseData.path, caseData.id);
  byId("caseBoundary").textContent = safeText(caseData.boundary);
  byId("caseStatus").textContent = safeText(caseData.status);
  byId("caseStatus").classList.toggle("is-danger", caseData.status === "HOLD");
}

function renderFindings(caseData) {
  if (!caseData.findings.some((item) => item.id === state.selectedFindingId)) {
    state.selectedFindingId = caseData.findings[0]?.id || "";
  }
  const list = byId("findingList");
  list.innerHTML = caseData.findings
    .map(
      (item) => `
        <button class="finding-row ${item.id === state.selectedFindingId ? "is-active" : ""}" type="button" data-finding-id="${escapeHtml(item.id)}">
          <span class="finding-index">${escapeHtml(item.code)}</span>
          <span class="finding-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.subtitle)}</small></span>
          <span class="finding-value">${escapeHtml(item.value)}</span>
        </button>`,
    )
    .join("");
  list.querySelectorAll("[data-finding-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedFindingId = button.dataset.findingId;
      renderFindings(caseData);
    });
  });
  renderFindingDetail(caseData);
}

function renderFindingDetail(caseData) {
  const finding = caseData.findings.find((item) => item.id === state.selectedFindingId);
  const detail = byId("findingDetail");
  if (!finding) {
    detail.innerHTML = "<p>当前 snapshot 未包含 finding 明细。</p>";
    return;
  }
  detail.innerHTML = `
    <div class="detail-kicker"><span>${escapeHtml(finding.id)}</span><span>${escapeHtml(finding.status)}</span></div>
    <h3>${escapeHtml(finding.title)}</h3>
    <p>${escapeHtml(finding.summary)}</p>
    <div class="detail-grid">
      <div><span>evidence_scope</span><strong>${escapeHtml(finding.scope)}</strong></div>
      <div><span>disposition</span><strong>${escapeHtml(finding.disposition)}</strong></div>
    </div>`;
}

function renderOrders(caseData) {
  const orders = caseData.orders;
  byId("orderSummary").innerHTML = `
    <div class="order-banner">
      <div class="detail-kicker"><span>STRUCTURED QUEUE</span><span>${escapeHtml(orders.status)}</span></div>
      <h3>${escapeHtml(orders.title)}</h3>
      <p>${escapeHtml(orders.description)}</p>
    </div>
    <div class="order-metrics">
      ${orders.metrics
        .map(
          (metric) => `<div class="order-metric"><span>${escapeHtml(metric.label)}</span><strong>${escapeHtml(metric.value)}</strong></div>`,
        )
        .join("")}
    </div>
    <article class="finding-detail">
      <div class="detail-kicker"><span>BOUNDARY</span><span>READONLY</span></div>
      <p>${escapeHtml(orders.boundary)}</p>
    </article>`;
}

function renderLineage(caseData) {
  const nodes = caseData.lineage.nodes;
  if (!nodes.some((item) => item.id === state.selectedLineageId && item.available !== false)) {
    state.selectedLineageId = nodes.find((item) => item.available !== false)?.id || "";
  }
  const canvas = byId("lineageCanvas");
  const nodeMarkup = (item) => `
    <button class="lineage-node ${item.id === state.selectedLineageId ? "is-active" : ""}" type="button" data-lineage-id="${escapeHtml(item.id)}" ${item.available === false ? "disabled" : ""}>
      <span>${escapeHtml(item.role)}</span>
      <strong>${escapeHtml(item.title)}</strong>
      <small>${escapeHtml(item.value)}</small>
    </button>`;
  canvas.innerHTML = nodes
    .map((item, index) => {
      const edge = index < nodes.length - 1 ? `<div class="lineage-edge" title="${escapeHtml(caseData.lineage.edge_label)}"></div>` : "";
      return nodeMarkup(item) + edge;
    })
    .join("");
  canvas.querySelectorAll("[data-lineage-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedLineageId = button.dataset.lineageId;
      renderLineage(caseData);
    });
  });
  const node = nodes.find((item) => item.id === state.selectedLineageId) || nodes[0];
  byId("lineageDetail").innerHTML = node
    ? `<div class="detail-kicker"><span>${escapeHtml(node.role)}</span><span>${escapeHtml(node.status)}</span></div>
       <h3>${escapeHtml(node.title)} · ${escapeHtml(node.value)}</h3>
       <p>${escapeHtml(node.detail)}</p>`
    : "<p>当前 snapshot 未提供 lineage。</p>";
}

function renderPhases(caseData) {
  byId("phaseProgress").textContent = safeText(caseData.phase_progress);
  byId("phaseStepper").innerHTML = caseData.phases
    .map(
      (item, index) => `
        <li class="phase-item is-${escapeHtml(item.status)}">
          <span class="phase-marker">${String(index + 1).padStart(2, "0")}</span>
          <span class="phase-copy"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)}</small></span>
          <span class="phase-state">${escapeHtml(item.status)}</span>
        </li>`,
    )
    .join("");
}

function renderTrace(caseData) {
  byId("traceAccordion").innerHTML = caseData.traces
    .map(
      (item, index) => `
        <details ${index === 0 ? "open" : ""}>
          <summary>
            <span class="trace-summary-icon">${escapeHtml(item.code)}</span>
            <span class="trace-summary-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.subtitle)}</small></span>
            <span class="trace-badge ${item.status === "HOLD" || item.status === "RECAPTURE" ? "hold" : ""}">${escapeHtml(item.status)}</span>
          </summary>
          <pre class="trace-payload">${escapeHtml(item.payload)}</pre>
        </details>`,
    )
    .join("");
  byId("policyTerminal").innerHTML = `case_status=${escapeHtml(caseData.status)}<br>production=false<br>decision_authority=human_only<br>mode=reviewer_readonly`;
}

function renderProvider() {
  const provider = normalizeProvider(state.snapshot.external_model);
  byId("providerHost").textContent = provider.base_url;
  byId("providerMode").textContent = provider.mode;
  byId("providerKeyConfigured").textContent = String(provider.key_configured);
  byId("providerConnection").textContent = provider.connection_status;
  byId("providerStatus").textContent = provider.connection_status;
  byId("providerStatus").classList.toggle("is-connected", provider.connection_status === "CONNECTED");
}

function renderVisual() {
  const visual = state.snapshot.visual || FALLBACK_SNAPSHOT.visual;
  byId("measurementPin").textContent = `${safeText(visual.algorithm)} ${safeText(visual.observed)}`;
  byId("algorithmValue").textContent = safeText(visual.algorithm);
  byId("observedValue").textContent = safeText(visual.observed);
  byId("thresholdValue").textContent = safeText(visual.minimum);
  byId("visualBoundaryValue").textContent = safeText(visual.evidence_class, "synthetic only");
  byId("imageProvenance").textContent =
    state.source === "api"
      ? `${safeText(visual.label)} · initial=${safeText(visual.initial_decision)} · recheck=${safeText(visual.recheck_decision)}。${safeText(visual.boundary)}`
      : `Before 已证实测量：${safeText(visual.algorithm)} ${safeText(visual.observed)} < 阈值 ${safeText(visual.minimum)}。After 槽位不在 fallback 中声明 PASS。`;
  byId("rawSampleId").textContent = safeText(visual.sample_id);
  byId("rawFindingCode").textContent = safeText(visual.finding_code);
  byId("rawAlgorithm").textContent = safeText(visual.algorithm);
  byId("rawObservedMinimum").textContent = `${safeText(visual.observed)} / ${safeText(visual.minimum)}`;
  byId("rawMeanLuma").textContent = safeText(visual.mean_luma);
  byId("rawResult").textContent = safeText(visual.result);
  byId("rawBeforeSha").textContent = safeText(visual.before_sha256);
  byId("rawAfterSha").textContent = safeText(visual.after_sha256);
  byId("rawEvidenceClass").textContent = safeText(visual.evidence_class);
  byId("rawBoundary").textContent = safeText(visual.boundary);
}

function renderFooter(caseData) {
  byId("footerRelease").innerHTML = `<i class="footer-dot hold"></i>Release：${escapeHtml(caseData.status)}`;
  byId("footerSnapshot").textContent =
    state.source === "api" ? "Snapshot：API / schema validated" : "Snapshot：embedded fallback / API unavailable";
}

function renderAll() {
  const caseData = getCurrentCase();
  renderCaseList();
  renderHeader(caseData);
  renderFindings(caseData);
  renderOrders(caseData);
  renderLineage(caseData);
  renderPhases(caseData);
  renderTrace(caseData);
  renderProvider();
  renderVisual();
  renderFooter(caseData);
}

function selectCase(caseId) {
  const target = state.snapshot.cases.find((item) => item.id === caseId);
  if (!target) return;
  state.selectedCaseId = caseId;
  state.selectedFindingId = target.findings[0]?.id || "";
  state.selectedLineageId = target.lineage.nodes.find((item) => item.available !== false)?.id || "";
  renderAll();
}

function setEvidenceView(view) {
  if (!["findings", "orders", "lineage"].includes(view)) return;
  state.evidenceView = view;
  document.querySelectorAll("[data-evidence-view-button]").forEach((button) => {
    const active = button.dataset.evidenceViewButton === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-evidence-view]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.evidenceView === view);
  });
}

function setImageMode(mode) {
  if (!["before", "after", "split"].includes(mode)) return;
  state.imageMode = mode;
  document.querySelector(".image-workspace").dataset.imageView = mode;
  document.querySelectorAll("[data-image-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.imageMode === mode);
  });
}

function setMobilePanel(panelName) {
  if (!["explorer", "workspace", "trace"].includes(panelName)) return;
  state.mobilePanel = panelName;
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("is-mobile-active", panel.dataset.panel === panelName);
  });
  document.querySelectorAll("[data-mobile-panel]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mobilePanel === panelName);
  });
}

function setTheme(theme) {
  const normalized = theme === "dark" ? "dark" : "light";
  const dark = normalized === "dark";
  document.documentElement.dataset.theme = normalized;
  const button = byId("themeToggle");
  button.setAttribute("aria-pressed", String(dark));
  button.title = dark ? "切换为 Light 主题" : "切换为 Dark 主题";
  byId("themeLabel").textContent = dark ? "Light" : "Dark";
}

function bindStaticInteractions() {
  byId("themeToggle").addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  document.querySelectorAll("[data-image-mode]").forEach((button) => {
    button.addEventListener("click", () => setImageMode(button.dataset.imageMode));
  });
  document.querySelectorAll("[data-evidence-view-button]").forEach((button) => {
    button.addEventListener("click", () => setEvidenceView(button.dataset.evidenceViewButton));
  });
  document.querySelectorAll("[data-mobile-panel]").forEach((button) => {
    button.addEventListener("click", () => setMobilePanel(button.dataset.mobilePanel));
  });
  document.querySelectorAll("[data-focus-panel]").forEach((button) => {
    button.addEventListener("click", () => setMobilePanel(button.dataset.focusPanel));
  });
  document.querySelectorAll("[data-evidence-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      setMobilePanel("workspace");
      setEvidenceView(button.dataset.evidenceTab);
    });
  });
  document.querySelectorAll("[data-focus-view='visual']").forEach((button) => {
    button.addEventListener("click", () => {
      setMobilePanel("workspace");
      byId("visualStage").scrollIntoView({ block: "start" });
    });
  });
}

async function loadSnapshot() {
  try {
    const response = await fetch(SNAPSHOT_ENDPOINT, {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`snapshot request failed (${response.status})`);
    const snapshot = normalizeSnapshot(await response.json());
    state.snapshot = snapshot;
    state.source = "api";
    if (!snapshot.cases.some((item) => item.id === state.selectedCaseId)) {
      state.selectedCaseId = snapshot.cases[0].id;
    }
    byId("snapshotSource").textContent = "API snapshot · schema validated";
    document.documentElement.dataset.snapshotSource = "api";
  } catch {
    state.snapshot = FALLBACK_SNAPSHOT;
    state.source = "fallback";
    byId("snapshotSource").textContent = "Embedded fallback · API unavailable";
    document.documentElement.dataset.snapshotSource = "fallback";
  }
  renderAll();
}

function init() {
  setTheme("light");
  bindStaticInteractions();
  bindImageFallback("before");
  bindImageFallback("after");
  setEvidenceView(state.evidenceView);
  setImageMode(state.imageMode);
  setMobilePanel(state.mobilePanel);
  renderAll();
  void loadSnapshot();
}

document.addEventListener("DOMContentLoaded", init);
