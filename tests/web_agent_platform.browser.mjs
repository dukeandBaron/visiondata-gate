/** Browser component + actual receipt client regression. All transport is synthetic.
 * Run with installed Playwright: VDG_PLAYWRIGHT_MODULE=<.../playwright/index.mjs>
 * node --test tests/web_agent_platform.browser.mjs
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(repoRoot, "web");
const requireWeb = createRequire(path.join(webRoot, "package.json"));
const { build, transformWithOxc } = await import(pathToFileURL(requireWeb.resolve("vite")).href);
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || requireWeb.resolve("playwright")).href);
let browser;
let bundle;

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",")}}`;
  return JSON.stringify(value);
}
function signed(value, header) {
  const receipt_sha256 = createHash("sha256").update(canonical(value) + "\n").digest("hex");
  return { payload: { ...value, receipt_sha256 }, headers: { [header]: receipt_sha256, ETag: `"${receipt_sha256}"` } };
}
const scope = { workspace_id: "wsp_platform_test", project_id: "prj_platform_test" };
const taskId = "task_platform_test";
const overviewPath = `/v1/workspaces/${scope.workspace_id}/agent-platform?project_id=${scope.project_id}`;
const recoveryPath = `/v1/tasks/${taskId}/execution-recovery`;
const usagePath = `/v1/tasks/${taskId}/model-usage`;
const product = { activeWorkspace: { workspace_id: scope.workspace_id, name: "Test workspace" },
  activeProject: { project_id: scope.project_id, name: "Test project" } };
function overview(override = {}) {
  return signed({ schema_version: "visiondata-gate.agent-platform.v1", ...scope,
    scope: { mode: "LOCAL_WORKSPACE", production_authentication: false },
    capabilities: [{ capability_id: "tool:test", name: "Deterministic test tool", kind: "TOOL", status: "REGISTERED_LOCAL", description: "Local test measurements" }],
    providers: { configured_count: 2, enabled_count: 1, connection_status: "NOT_PROBED" },
    tasks: [{ task_id: taskId, goal: "Recover test task", execution_status: "RUNNING", final_decision: null, updated_at: "2026-09-09T10:00:00Z" }],
    task_count: 1, task_limit: 200, tasks_truncated: false, ...override }, "X-Agent-Platform-SHA256");
}
function recovery(override = {}) {
  return signed({ schema_version: "visiondata-gate.task-execution-recovery.v1", ...scope, task_id: taskId,
    execution_status: "RUNNING", classification: "INTERRUPTED", can_recover: true, reason_codes: ["OWNER_ENDED"],
    task_snapshot_sha256: "a".repeat(64), ...override }, "X-Execution-Recovery-SHA256");
}
function usage(override = {}) {
  return signed({ schema_version: "visiondata-gate.task-model-usage.v1", ...scope, task_id: taskId,
    task_request_sha256: "a".repeat(64), task_evidence_sha256: null, task_trace_sha256: null,
    records: [], summary: { accounting_scope: "TASK_CORE_AND_SAVED_INCIDENT_PLANNERS_REMOTE_ONLY", call_status: "UNKNOWN",
      logical_model_calls: null, transport_attempts: null, successful_responses: null, local_model_calls: null,
      replay_receipt_count: 0, input_tokens: null, output_tokens: null, total_tokens: null, usage_completeness: "UNAVAILABLE",
      unreported_receipt_count: 0, unreported_attempt_count: 0, pricing_status: "NOT_CONFIGURED", cost: null, currency: null },
    unavailable_reasons: ["TASK_NOT_COMPLETED"], includes_secrets_or_prompts: false, estimates_counted_as_usage: false,
    boundary_notice: "Synthetic test saved evidence only", ...override }, "X-Model-Usage-SHA256");
}
const apiMock = `
  export class OperatorApiError extends Error {
    constructor(code, message, status) { super(message); this.code=code; this.status=status; }
  }
  export async function operatorFetch(path, init={}) {
    const method=init.method||'GET';
    window.__calls.push({path, method, body:init.body?JSON.parse(init.body):null});
    const response=window.__responses[method+' '+path];
    if (!response) throw new OperatorApiError('HTTP_404', 'Synthetic response is not available', 404);
    if (response.error) throw new OperatorApiError('HTTP_502', 'Synthetic transport unavailable', 502);
    const make=()=>new Response(JSON.stringify(response.payload),{headers:response.headers});
    if (response.hold) return new Promise(resolve=>{window.__resolveHeld=()=>resolve(make());});
    return make();
  }
`;
const entry = `
  import {useState} from 'react';
  import {createRoot} from 'react-dom/client';
  import {MemoryRouter} from 'react-router-dom';
  import {AgentPlatformPage} from '/src/pages/AgentPlatformPage.tsx';
  function Harness() {
    const [product,setProduct]=useState(window.__product);
    window.__product=product;
    window.__setProduct=setProduct;
    return <MemoryRouter initialEntries={[window.__route]}><AgentPlatformPage/></MemoryRouter>;
  }
  createRoot(document.getElementById('root')).render(<Harness/>);
`;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: "error",
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: "/__platform_test.tsx", name: "PlatformTest", formats: ["iife"] } },
    plugins: [{ name: "isolated-platform", enforce: "pre",
      resolveId(id) {
        if (id.endsWith("__platform_test.tsx")) return "\0platform-entry.tsx";
        if (id.endsWith("/ProductContext")) return "\0platform-context";
        if (id.endsWith("/data/api") || id === "./api") return "\0platform-api";
      },
      load(id) {
        if (id === "\0platform-entry.tsx") return entry;
        if (id === "\0platform-context") return "export function useProduct(){return window.__product;}";
        if (id === "\0platform-api") return apiMock;
      },
      transform(code, id) { if (id === "\0platform-entry.tsx") return transformWithOxc(code, id.slice(1), { lang: "tsx", jsx: { runtime: "automatic" } }); },
    }],
  });
  bundle = (Array.isArray(result) ? result[0] : result).output.find((item) => item.type === "chunk").code;
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || [
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe",
  ].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});
after(async () => { await browser?.close(); });

async function openPage(responses = {}, options = {}) {
  const page = await browser.newPage();
  page.setDefaultTimeout(10_000);
  page.on("pageerror", (error) => console.error("Platform test page error:", error.message));
  await page.route("http://127.0.0.1:19891/**", (route) => route.fulfill({ contentType: "text/html", body: '<!doctype html><div id="root"></div>' }));
  await page.goto("http://127.0.0.1:19891/test");
  await page.evaluate(({ responses, options, product }) => {
    window.__responses=responses; window.__product=options.product||product;
    window.__route=options.route||'/platform'; window.__calls=[];
  }, { responses: { ["GET " + overviewPath]: overview(), ["GET " + recoveryPath]: recovery(), ["GET " + usagePath]: usage(), ...responses }, options, product });
  await page.addScriptTag({ content: bundle });
  return page;
}

test("verified platform distinguishes provider configuration from probing", async () => {
  const page = await openPage();
  try {
    await page.getByText("当前项目回执已核验", { exact: true }).waitFor();
    assert.equal(await page.getByText("1 启用 / 2 已配置", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("连接尚未实测 · NOT_PROBED", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("Deterministic test tool", { exact: true }).isVisible(), true);
  } finally { await page.close(); }
});

test("workflow opens visual training separately from the CPU reference loop", async () => {
  const page = await openPage();
  try {
    await page.getByText("当前项目回执已核验", { exact: true }).waitFor();
    const workflow = page.getByRole("region", { name: "视觉数据与模型工作流" });
    await workflow.getByText("第一次使用？查看数据到模型的操作顺序", { exact: true }).click();
    const training = workflow.getByRole("link", { name: /训练、评测与回流/ });
    assert.equal(await training.getAttribute("href"), "/models?tab=vision");
    assert.equal(await workflow.getByRole("link", { name: "CPU 参考学习闭环" }).getAttribute("href"), "/learning");
    assert.equal(await page.getByText(/生产身份认证尚未接入/).count(), 0);
  } finally { await page.close(); }
});

test("missing workspace selection makes no API request and shows no zero totals", async () => {
  const page = await openPage({}, { product: {} });
  try {
    await page.getByRole("heading", { name: "请先选择工作空间和项目" }).waitFor();
    assert.equal(await page.evaluate(() => window.__calls.length), 0);
    assert.equal(await page.locator(".agent-platform-metrics").count(), 0);
  } finally { await page.close(); }
});

for (const [name, response] of [
  ["wrong workspace", overview({ workspace_id: "wsp_other" })],
  ["wrong project", overview({ project_id: "prj_other" })],
  ["tampered payload", { ...overview(), payload: { ...overview().payload, task_count: 80 } }],
  ["missing response SHA", { ...overview(), headers: { ETag: overview().headers.ETag } }],
  ["weak ETag", { ...overview(), headers: { ...overview().headers, ETag: "W/" + overview().headers.ETag } }],
  ["transport error", { error: true }],
]) {
  test(`platform rejects ${name} without showing counts or task details`, async () => {
    const page = await openPage({ ["GET " + overviewPath]: response });
    try {
      await page.getByRole("heading", { name: "平台状态暂不可确认" }).waitFor();
      assert.equal(await page.locator(".agent-platform-metrics").count(), 0);
      assert.equal(await page.locator(".agent-platform-task-list").count(), 0);
      assert.equal(await page.evaluate(() => window.__calls.length), 1);
    } finally { await page.close(); }
  });
}

test("a task deep link outside the verified scope never requests its details", async () => {
  const page = await openPage({}, { route: "/platform?task=task_other" });
  try {
    await page.getByText(/指定任务不在当前项目的已验证列表中/).waitFor();
    assert.equal(await page.evaluate(() => window.__calls.length), 1);
  } finally { await page.close(); }
});

test("interrupted recovery requires manual identity, note and checkbox; returns an unstarted task", async () => {
  const replacement = signed({ schema_version: "visiondata-gate.task-execution-recovery-receipt.v1", ...scope, task_id: taskId,
    replacement_task_id: "task_replacement", original_snapshot_sha256: "a".repeat(64), failed_task_snapshot_sha256: "b".repeat(64),
    replacement_task_snapshot_sha256: "c".repeat(64), reviewer_identity: "Test reviewer", note: "Confirmed interrupted owner",
    recovered_by: "test_actor", recovered_at: "2026-09-09T10:01:00Z", requires_new_plan_approval: true, auto_started: false }, "X-Execution-Recovery-SHA256");
  const page = await openPage({ ["POST " + recoveryPath]: replacement }, { route: `/platform?task=${taskId}` });
  try {
    const submit = page.getByRole("button", { name: "具名创建替代任务", exact: true });
    await submit.waitFor();
    assert.equal(await submit.isDisabled(), true);
    await page.getByLabel("恢复复核人", { exact: true }).fill("Test reviewer");
    await page.getByLabel("恢复依据", { exact: true }).fill("Confirmed interrupted owner");
    assert.equal(await submit.isDisabled(), true);
    await page.getByRole("checkbox").check();
    await submit.click();
    await page.getByText("替代任务已创建，等待新计划审批。", { exact: true }).waitFor();
    assert.equal(await page.getByRole("link", { name: "打开替代任务并人工审批" }).getAttribute("href"), "/command-center?task=task_replacement");
    const writes = await page.evaluate(() => window.__calls.filter((call) => call.method === "POST"));
    assert.equal(writes.length, 1);
    assert.deepEqual(writes[0].body, { expected_snapshot_sha256: "a".repeat(64), reviewer_identity: "Test reviewer", note: "Confirmed interrupted owner", operator_attests_recovery: true });
    assert.equal(writes.some((call) => /execute|approval|start/.test(call.path)), false);
  } finally { await page.close(); }
});

test("legacy unknown ownership cannot expose a recovery form", async () => {
  const page = await openPage({ ["GET " + recoveryPath]: recovery({ classification: "LEGACY_UNKNOWN", can_recover: false }) }, { route: `/platform?task=${taskId}` });
  try {
    await page.getByText("LEGACY_UNKNOWN", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "具名创建替代任务" }).count(), 0);
  } finally { await page.close(); }
});

test("late results from a previous project cannot replace the current scope", async () => {
  const newScope = { workspace_id: "wsp_new", project_id: "prj_new" };
  const newPath = `/v1/workspaces/${newScope.workspace_id}/agent-platform?project_id=${newScope.project_id}`;
  const page = await openPage({ ["GET " + overviewPath]: { ...overview(), hold: true },
    ["GET " + newPath]: overview({ ...newScope, providers: { configured_count: 7, enabled_count: 3, connection_status: "NOT_PROBED" } }) });
  try {
    await page.waitForFunction(() => typeof window.__resolveHeld === "function");
    await page.evaluate((newScope) => window.__setProduct({ activeWorkspace: { workspace_id: newScope.workspace_id, name: "New workspace" },
      activeProject: { project_id: newScope.project_id, name: "New project" } }), newScope);
    await page.getByText("3 启用 / 7 已配置", { exact: true }).waitFor();
    await page.evaluate(() => window.__resolveHeld());
    assert.equal(await page.getByText("1 启用 / 2 已配置", { exact: true }).isVisible(), false);
    assert.equal(await page.getByText("3 启用 / 7 已配置", { exact: true }).isVisible(), true);
  } finally { await page.close(); }
});

test("unknown or unavailable usage never becomes zero cost or tokens", async () => {
  const page = await openPage({}, { route: `/platform?task=${taskId}` });
  try {
    await page.getByText(/用量回执已核验/).waitFor();
    const values = await page.locator(".agent-platform-usage .metric > strong").allTextContents();
    assert.deepEqual(values, ["未知", "未知", "未知", "未配置计价"]);
    assert.equal(await page.getByText(/缺失依据：TASK_NOT_COMPLETED/).isVisible(), true);
  } finally { await page.close(); }
});

test("retry partial usage does not aggregate the final response or input estimate", async () => {
  const report = usage().payload;
  delete report.receipt_sha256;
  const response = usage({ ...report, unavailable_reasons: [],
    summary: { ...report.summary, call_status: "CALLS_RECORDED", logical_model_calls: 1, transport_attempts: 2,
      successful_responses: 1, local_model_calls: 0, usage_completeness: "PARTIAL", unreported_receipt_count: 1, unreported_attempt_count: 1 },
    records: [{ source_kind: "INCIDENT_PLANNER", case_id: "case_test", case_sha256: "b".repeat(64), source_receipt_sha256: "c".repeat(64),
      transport_receipt_sha256: "d".repeat(64), origin: "REMOTE", planner_mode: "gated", outcome: "RESPONSE_RECORDED",
      logical_model_calls: 1, transport_attempts: 2, successful_responses: 1, input_tokens: 100, output_tokens: 20, total_tokens: 120,
      estimated_input_tokens: 8000, unreported_attempt_count: 1, usage_completeness: "PARTIAL", token_scope: "PROVIDER_FINAL_RESPONSE" }] });
  const page = await openPage({ ["GET " + usagePath]: response }, { route: `/platform?task=${taskId}` });
  try {
    await page.getByText(/用量回执已核验/).waitFor();
    assert.deepEqual(await page.locator(".agent-platform-usage .metric > strong").allTextContents(), ["1", "2", "未知", "未配置计价"]);
    await page.getByText("查看 1 条用量来源", { exact: true }).click();
    assert.equal(await page.getByText("预估输入 8000 Token，仅为估算，未计入实际用量。", { exact: true }).isVisible(), true);
  } finally { await page.close(); }
});

test("a usage response from another task is rejected independently of recovery", async () => {
  const page = await openPage({ ["GET " + usagePath]: usage({ task_id: "task_other" }) }, { route: `/platform?task=${taskId}` });
  try {
    await page.getByText(/用量 UNKNOWN/).waitFor();
    assert.equal(await page.locator(".agent-platform-usage .metric").count(), 0);
    assert.equal(await page.getByRole("button", { name: "具名创建替代任务", exact: true }).isVisible(), true);
  } finally { await page.close(); }
});

test("a failed recovery write is not automatically replayed", async () => {
  const page = await openPage({ ["POST " + recoveryPath]: { error: true } }, { route: `/platform?task=${taskId}` });
  try {
    const submit = page.getByRole("button", { name: "具名创建替代任务", exact: true });
    await submit.waitFor();
    await page.getByLabel("恢复复核人", { exact: true }).fill("Test reviewer");
    await page.getByLabel("恢复依据", { exact: true }).fill("Confirmed interruption");
    await page.getByRole("checkbox").check();
    await submit.click();
    await page.getByText(/恢复结果尚未核实，已停止重复提交/).waitFor();
    assert.equal(await submit.isDisabled(), true);
    assert.equal(await page.evaluate(() => window.__calls.filter((call) => call.method === "POST").length), 1);
    assert.equal(await page.getByRole("link", { name: "打开替代任务并人工审批" }).count(), 0);
  } finally { await page.close(); }
});

test("public entry graph excludes the private platform module", () => {
  const publicApp = readFileSync(path.join(webRoot, "src/public/PublicApp.tsx"), "utf8");
  assert.equal(publicApp.includes("AgentPlatformPage"), false);
  assert.match(publicApp, /path="\*" element=\{<Navigate to="\/" replace/);
});
