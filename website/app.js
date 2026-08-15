const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const FALLBACK_DATA = {
  receipt_sha256: "bb2a23e4a154db4123ba4f9682ce22ba470af5e1a6b89d4c5c4977c359cda110",
  pilot: { fixed_image_denominator: 180, dynamic_worker_count: 3, work_order_count: 45 },
  rule_checks: [],
};

const nodeDetails = {
  intake: {
    kicker: "INTAKE / CONTRACT",
    title: "任务合同冻结",
    body: "固定公开图像分母、审核阈值、工具范围与发布目标，避免运行后更换口径。",
    metrics: [["输入分母", "180"], ["发布范围", "沙箱训练池"]],
    proof: "contract / Omni-180-v1",
  },
  tools: {
    kicker: "STATIC WAVE / 5 TOOLS",
    title: "五类工具并行取证",
    body: "质量、重复与泄漏、标注、覆盖和治理工具只报告可测事实；任何必需工具失败都会关闭门禁。",
    metrics: [["工具数量", "5"], ["工具错误", "0"]],
    proof: "tool_trace / all-ok",
  },
  judge1: {
    kicker: "FIRST JUDGE PASS",
    title: "第一次裁决形成中间证据",
    body: "冻结 Policy Judge 先汇总首轮 finding 与动作，再把新出现的漂移、分组和冲突交给 Leader。",
    metrics: [["初始结论", "RECAPTURE"], ["依据", "冻结规则包"]],
    proof: "policy / industrial-v1",
  },
  leader: {
    kicker: "DYNAMIC LEADER / REPLAN ×1",
    title: "证据改变后续任务",
    body: "Leader 不重复固定 DAG，而是根据首轮证据创建三个此前不存在的只读补证任务，并行派发。",
    metrics: [["重规划", "1 次"], ["新增 Worker", "3"]],
    proof: "dynamic_leader_plan.json",
  },
  conflict: {
    kicker: "DYNAMIC WORKER / CONFLICT",
    title: "跨工具动作冲突复核",
    body: "2 个样本同时收到不一致处置。系统增派冲突复核 Worker，并把结果转为 INVESTIGATE。",
    metrics: [["冲突样本", "2"], ["处置", "INVESTIGATE"]],
    proof: "followup.cross-tool-conflict-adjudication",
  },
  metadata: {
    kicker: "DYNAMIC WORKER / METADATA",
    title: "metadata 数量对账",
    body: "文件树与 metadata 相差 15 张、涉及 3 类。Worker 保留调查工单，禁止自动补写或猜测。",
    metrics: [["数量漂移", "15"], ["涉及类别", "3"]],
    proof: "followup.metadata-reconciliation",
  },
  resolution: {
    kicker: "DYNAMIC WORKER / RESOLUTION",
    title: "原生分辨率分组补证",
    body: "发现 28 个原生尺寸组后，新增 Worker 按组测量质量，再把补充证据送回复判。",
    metrics: [["尺寸组", "28"], ["补证状态", "ACCEPTED"]],
    proof: "followup.native-resolution-reconciliation",
  },
  judge2: {
    kicker: "FROZEN POLICY JUDGE",
    title: "完整证据下正确阻断",
    body: "8 项交付完整性检查均通过，但完整证据确认批次仍需整改，因此业务结论保持 RECAPTURE。",
    metrics: [["完整性检查", "8/8 PASS"], ["业务结论", "RECAPTURE"]],
    proof: "omni_gate_result.json",
  },
  delivery: {
    kicker: "DELIVERY / TRACEABLE",
    title: "finding 转成可执行工单",
    body: "45 条 finding 一一映射为 45 张整改工单，并交付规则检查、reason trace 与 SHA-256 凭证。",
    metrics: [["findings", "45"], ["work orders", "45"]],
    proof: "scenario_delivery_receipt.json",
  },
};

const graphNodes = [
  { id: "intake", x: 0.08, y: 0.16, label: "任务合同", sub: "180 fixed", kind: "static" },
  { id: "tools", x: 0.27, y: 0.16, label: "工具波次", sub: "5 read-only", kind: "static" },
  { id: "judge1", x: 0.47, y: 0.16, label: "首轮裁决", sub: "evidence", kind: "decision" },
  { id: "leader", x: 0.66, y: 0.16, label: "Leader", sub: "replan ×1", kind: "leader" },
  { id: "conflict", x: 0.21, y: 0.67, label: "冲突复核", sub: "2 samples", kind: "dynamic" },
  { id: "metadata", x: 0.46, y: 0.67, label: "metadata 对账", sub: "drift 15", kind: "dynamic" },
  { id: "resolution", x: 0.71, y: 0.67, label: "分辨率补证", sub: "28 groups", kind: "dynamic" },
  { id: "judge2", x: 0.86, y: 0.16, label: "复判", sub: "RECAPTURE", kind: "decision" },
  { id: "delivery", x: 0.89, y: 0.68, label: "证据交付", sub: "45 orders", kind: "delivery" },
];

const graphEdges = [
  ["intake", "tools", "static"], ["tools", "judge1", "static"], ["judge1", "leader", "static"],
  ["leader", "judge2", "static"], ["leader", "conflict", "dynamic"], ["leader", "metadata", "dynamic"],
  ["leader", "resolution", "dynamic"], ["conflict", "judge2", "dynamic"], ["metadata", "judge2", "dynamic"],
  ["resolution", "judge2", "dynamic"], ["judge2", "delivery", "decision"],
];

class EvidenceCanvas {
  constructor(canvas, onSelect) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSelect = onSelect;
    this.selected = "intake";
    this.hovered = null;
    this.t = 0;
    this.width = 0;
    this.height = 0;
    this.dpr = 1;
    this.boxes = new Map();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas.parentElement);
    canvas.addEventListener("pointermove", (event) => this.pointer(event));
    canvas.addEventListener("pointerleave", () => { this.hovered = null; canvas.style.cursor = "default"; });
    canvas.addEventListener("click", (event) => this.click(event));
    this.resize();
    this.frame = this.frame.bind(this);
    requestAnimationFrame(this.frame);
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(320, rect.width);
    this.height = Math.max(340, rect.height);
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.layout();
  }

  layout() {
    this.boxes.clear();
    const compact = this.width < 530;
    const nodeW = compact ? 74 : Math.min(104, this.width * 0.135);
    const nodeH = compact ? 48 : 54;
    for (const node of graphNodes) {
      const x = 16 + node.x * (this.width - 32);
      const y = 28 + node.y * (this.height - 76);
      this.boxes.set(node.id, { x: x - nodeW / 2, y: y - nodeH / 2, w: nodeW, h: nodeH, cx: x, cy: y });
    }
  }

  pointer(event) {
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.hovered = null;
    for (const [id, box] of this.boxes) {
      if (x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h) this.hovered = id;
    }
    this.canvas.style.cursor = this.hovered ? "pointer" : "default";
  }

  click(event) {
    this.pointer(event);
    if (this.hovered) this.select(this.hovered);
  }

  select(id) {
    if (!this.boxes.has(id)) return;
    this.selected = id;
    this.onSelect(id);
  }

  endpoint(box, toward) {
    const dx = toward.cx - box.cx;
    const dy = toward.cy - box.cy;
    const scale = 1 / Math.max(Math.abs(dx) / (box.w / 2), Math.abs(dy) / (box.h / 2), 1);
    return { x: box.cx + dx * scale, y: box.cy + dy * scale };
  }

  edge(fromId, toId, kind, progress) {
    const ctx = this.ctx;
    const fromBox = this.boxes.get(fromId);
    const toBox = this.boxes.get(toId);
    const from = this.endpoint(fromBox, toBox);
    const to = this.endpoint(toBox, fromBox);
    const color = kind === "dynamic" ? "rgba(128,103,255,.5)" : kind === "decision" ? "rgba(255,166,64,.48)" : "rgba(75,116,170,.42)";
    const curve = Math.abs(to.y - from.y) > 90;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = kind === "dynamic" ? 1.35 : 1;
    ctx.setLineDash(kind === "dynamic" ? [4, 5] : []);
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    if (curve) {
      const midY = (from.y + to.y) / 2;
      ctx.bezierCurveTo(from.x, midY, to.x, midY, to.x, to.y);
    } else {
      ctx.lineTo(to.x, to.y);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    const angle = curve ? Math.atan2(to.y - (from.y + to.y) / 2, to.x - to.x) : Math.atan2(to.y - from.y, to.x - from.x);
    ctx.translate(to.x, to.y);
    ctx.rotate(Number.isFinite(angle) ? angle : Math.PI / 2);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(-7, -3.3); ctx.lineTo(0, 0); ctx.lineTo(-7, 3.3); ctx.closePath(); ctx.fill();
    ctx.restore();

    if (kind === "dynamic") {
      const p = (progress + (fromId.length % 5) * 0.13) % 1;
      const x = from.x + (to.x - from.x) * p;
      const y = from.y + (to.y - from.y) * p;
      ctx.save();
      ctx.fillStyle = "rgba(151,132,255,.9)";
      ctx.shadowBlur = 12;
      ctx.shadowColor = "#7057ff";
      ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }
  }

  node(node) {
    const ctx = this.ctx;
    const box = this.boxes.get(node.id);
    const selected = this.selected === node.id;
    const hovered = this.hovered === node.id;
    const palette = {
      static: ["rgba(11,36,74,.94)", "#365f92", "#b7c9e1"],
      dynamic: ["rgba(52,39,112,.94)", "#7057ff", "#d3caff"],
      decision: ["rgba(73,46,18,.95)", "#dd8c2d", "#ffd9a4"],
      leader: ["rgba(14,53,111,.96)", "#2475ef", "#bcd6ff"],
      delivery: ["rgba(12,66,57,.96)", "#1aa67a", "#baf0df"],
    }[node.kind];
    ctx.save();
    ctx.shadowBlur = selected ? 26 : hovered ? 16 : 0;
    ctx.shadowColor = palette[1];
    const radius = 10;
    ctx.beginPath();
    ctx.roundRect(box.x, box.y, box.w, box.h, radius);
    ctx.fillStyle = palette[0]; ctx.fill();
    ctx.strokeStyle = selected ? palette[1] : hovered ? `${palette[1]}cc` : `${palette[1]}78`;
    ctx.lineWidth = selected ? 1.8 : 1; ctx.stroke();
    ctx.shadowBlur = 0;
    if (selected) {
      ctx.fillStyle = palette[1];
      ctx.fillRect(box.x, box.y + 11, 2, box.h - 22);
    }
    const compact = this.width < 530;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = palette[2];
    ctx.font = `600 ${compact ? 9.5 : 10.5}px Inter, "Microsoft YaHei", sans-serif`;
    ctx.fillText(compact ? node.label.replace("metadata ", "meta ") : node.label, box.cx, box.cy - 7);
    ctx.fillStyle = palette[2] + "99";
    ctx.font = `${compact ? 7.5 : 8}px "SFMono-Regular", Consolas, monospace`;
    ctx.fillText(node.sub, box.cx, box.cy + 10);
    ctx.restore();
  }

  frame(time) {
    this.t = time / 1000;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.strokeStyle = "rgba(67,97,139,.11)";
    ctx.lineWidth = 1;
    const grid = 28;
    for (let x = 0; x <= this.width; x += grid) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.height); ctx.stroke(); }
    for (let y = 0; y <= this.height; y += grid) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.width, y); ctx.stroke(); }
    ctx.restore();

    for (const [from, to, kind] of graphEdges) this.edge(from, to, kind, (this.t * 0.19) % 1);
    for (const node of graphNodes) this.node(node);
    requestAnimationFrame(this.frame);
  }
}

function updateInspector(id) {
  const detail = nodeDetails[id];
  if (!detail) return;
  $("[data-inspector-kicker]").textContent = detail.kicker;
  $("[data-inspector-title]").textContent = detail.title;
  $("[data-inspector-body]").textContent = detail.body;
  $("[data-inspector-proof]").textContent = detail.proof;
  $("[data-inspector-metrics]").innerHTML = detail.metrics
    .map(([key, value]) => `<div><dt>${key}</dt><dd>${value}</dd></div>`)
    .join("");
  $$("[data-focus]").forEach((button) => button.classList.toggle("active", button.dataset.focus === id));
}

function renderData(data) {
  const pilot = data.pilot || FALLBACK_DATA.pilot;
  const stats = {
    images: pilot.fixed_image_denominator,
    workers: pilot.dynamic_worker_count,
    orders: pilot.work_order_count,
  };
  Object.entries(stats).forEach(([key, value]) => {
    $$(`[data-stat="${key}"]`).forEach((element) => { element.textContent = String(value); });
  });
  const receipt = data.receipt_sha256 || FALLBACK_DATA.receipt_sha256;
  $("[data-receipt-short]").textContent = `${receipt.slice(0, 8)}…${receipt.slice(-4)}`;
  const ruleList = $("[data-rule-list]");
  const rules = data.rule_checks || [];
  ruleList.innerHTML = rules.length
    ? rules.map((rule) => `<li title="${rule.id}"><span></span>${rule.label}</li>`).join("")
    : "<li><span></span>8 项发布完整性检查已通过</li>";
}

async function loadData() {
  try {
    const response = await fetch("data/site-data.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    console.warn("Using embedded fallback data", error);
    return FALLBACK_DATA;
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const header = $("[data-header]");
  const nav = $("#primary-nav");
  const navToggle = $(".nav-toggle");
  window.addEventListener("scroll", () => header.classList.toggle("scrolled", window.scrollY > 12), { passive: true });
  navToggle.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(open));
  });
  $$("a", nav).forEach((link) => link.addEventListener("click", () => {
    nav.classList.remove("open");
    navToggle.setAttribute("aria-expanded", "false");
  }));

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => { if (entry.isIntersecting) entry.target.classList.add("visible"); });
  }, { threshold: 0.08, rootMargin: "0px 0px -30px" });
  $$(".reveal").forEach((element, index) => {
    element.style.transitionDelay = `${Math.min(index % 4, 3) * 55}ms`;
    observer.observe(element);
  });

  const data = await loadData();
  renderData(data);

  const canvas = new EvidenceCanvas($("#evidence-canvas"), updateInspector);
  $$("[data-focus]").forEach((button) => button.addEventListener("click", () => canvas.select(button.dataset.focus)));
  updateInspector("intake");
});
