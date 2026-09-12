/**
 * Isolated component regressions. API responses are deliberate test doubles;
 * these tests never connect to a user's API, workspace, images, or model.
 * Run: node --test tests/web_workflow_handoff.browser.mjs
 * Set VDG_PLAYWRIGHT_MODULE to the installed Playwright module if not local.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import { after, before, test } from "node:test";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(repoRoot, "web");
const webRequire = createRequire(path.join(webRoot, "package.json"));
const { build, transformWithOxc } = await import(pathToFileURL(webRequire.resolve("vite")).href);
const playwrightPath = process.env.VDG_PLAYWRIGHT_MODULE
  || webRequire.resolve("playwright");
const { chromium } = await import(pathToFileURL(playwrightPath).href);
let browser;
let componentBundle;

const contextMock = `
  export function useProduct() { return window.__scenario.product; }
`;
const apiMock = `
  export class OperatorApiError extends Error {
    constructor(message) { super(message); this.code = 'HTTP_502'; }
  }
  export async function listOperatorWorkOrders() {
    window.__calls.list += 1;
    if (window.__scenario.queueFailure) throw new OperatorApiError('本地工作台请求失败');
    return [];
  }
  export async function loadOperatorAnnotations() { throw new Error('Unexpected annotation call'); }
  export async function loadOperatorWorkOrderCrop() { throw new Error('Unexpected crop call'); }
  export async function updateOperatorWorkOrder() { throw new Error('Human mutation not permitted in test'); }
`;
const entry = `
  import { createRoot } from 'react-dom/client';
  import { useState } from 'react';
  import { MemoryRouter } from 'react-router-dom';
  import { CapaPage } from '/src/pages/CapaPage.tsx';
  import { OperatorAgentPanel } from '/src/components/OperatorAgentPanel.tsx';
  function Harness() {
    const [view, setView] = useState(window.__scenario.view || 'OVERVIEW');
    if (window.__scenario.component === 'capa') return <CapaPage />;
    return <OperatorAgentPanel
      asset={window.__scenario.asset} run={window.__scenario.run}
      turns={[]} loading={false} analyzing={false} asking={false}
      traceStale={Boolean(window.__scenario.traceStale)} revealedEventCount={10}
      activeView={view} onActiveViewChange={setView}
      onRun={() => { window.__calls.run += 1; }} onAsk={() => {}}
      onCreateWorkOrder={() => { window.__calls.create += 1; }}
      onHandoffProject={() => { window.__calls.handoff += 1; }}
      handoffPending={false} handoffDisabled={false}
      onOpenCapa={() => {}} onOpenEvidence={() => {}} onOpenTaskWorkbench={() => {}}
    />;
  }
  createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={[window.__scenario.route]}><Harness /></MemoryRouter>);
`;

before(async () => {
  const modules = new Map([
    ["\0workflow-context", contextMock],
    ["\0workflow-api", apiMock],
    ["\0workflow-controlled.tsx", "export function ControlledCapaWorkbench() { return <div data-testid='controlled-capa'>Controlled CAPA test boundary</div>; }"],
    ["\0workflow-entry.tsx", entry],
  ]);
  const result = await build({
    root: webRoot,
    configFile: false,
    logLevel: "error",
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: "/__workflow_entry.tsx", name: "WorkflowRegression", formats: ["iife"] } },
    plugins: [{
      name: "isolated-workflow-regressions",
      enforce: "pre",
      resolveId(id) {
        if (id.endsWith("__workflow_entry.tsx")) return "\0workflow-entry.tsx";
        if (id.endsWith("/ProductContext")) return "\0workflow-context";
        if (id.endsWith("/data/api")) return "\0workflow-api";
        if (id.endsWith("/components/ControlledCapaWorkbench")) return "\0workflow-controlled.tsx";
      },
      load(id) { return modules.get(id); },
      transform(code, id) {
        if (id.startsWith("\0workflow-") && id.endsWith(".tsx")) {
          return transformWithOxc(code, id.slice(1), { lang: "tsx", jsx: { runtime: "automatic" } });
        }
      },
    }],
  });
  componentBundle = (Array.isArray(result) ? result[0] : result).output.find((item) => item.type === "chunk").code;
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || [
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
  ].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});

after(async () => {
  await browser?.close();
});

const product = {
  activeWorkspace: { workspace_id: "wsp_test_only", name: "Test workspace" },
  activeProject: { project_id: "prj_test_only", name: "Test project", source_kind: "local_authorized_directory" },
};

async function openScenario(scenario, search = "") {
  const page = await browser.newPage();
  page.setDefaultTimeout(15_000);
  page.on("pageerror", (error) => console.error("Test page error:", error.message));
  await page.setContent('<!doctype html><html><body><div id="root"></div></body></html>');
  await page.evaluate((scenario) => {
    window.__scenario = scenario;
    window.__calls = { list: 0, create: 0, handoff: 0, run: 0 };
  }, { product, route: "/" + search, ...scenario });
  await page.addScriptTag({ content: componentBundle });
  return page;
}

test("CAPA failed read stays unknown; explicit retry can establish a true empty queue", async () => {
  const page = await openScenario({ component: "capa", queueFailure: true });
  try {
    await page.getByText("HTTP_502: 本地工作台请求失败", { exact: true }).waitFor();
    assert.equal(await page.getByText("工单数量暂不可确认", { exact: true }).isVisible(), true);
    assert.equal(await page.locator(".capa-live-deltas").innerText().then((text) => /\b0\b/.test(text)), false);
    assert.equal(await page.getByText(/^当前(?:工作空间没有工单|项目没有像素工单)$/).isVisible(), false);
    await page.evaluate(() => { window.__scenario.queueFailure = false; });
    await page.getByRole("button", { name: "重新读取工单", exact: true }).click();
    await page.getByText("当前项目没有像素工单", { exact: true }).waitFor();
    assert.match(await page.locator(".capa-live-deltas").innerText(), /0 Open/);
    assert.equal(await page.evaluate(() => window.__calls.list), 2);
  } finally { await page.close(); }
});

test("task deep link opens controlled CAPA instead of the unrelated pixel ledger", async () => {
  const page = await openScenario({ component: "capa" }, "?task=task_test_only");
  try {
    await page.getByRole("heading", { name: "CAPA 工单", exact: true }).waitFor();
    assert.equal(await page.getByTestId("controlled-capa").isVisible(), true);
    assert.equal(await page.locator(".capa-layer-view").isVisible(), false);
  } finally { await page.close(); }
});

test("missing workspace is a selection state, not evidence of zero work orders", async () => {
  const page = await openScenario({ component: "capa", product: {} });
  try {
    await page.getByRole("heading", { name: "CAPA 工单", exact: true }).waitFor();
    assert.equal(await page.getByText("请先选择工作空间和项目", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText(/^当前(?:工作空间没有工单|项目没有像素工单)$/).isVisible(), false);
    assert.equal(await page.evaluate(() => window.__calls.list), 0);
  } finally { await page.close(); }
});

const asset = {
  asset_id: "asset_test_only", workspace_id: "wsp_test_only", project_id: "prj_test_only",
  original_name: "duplicate-test.png", source_sha256: "a".repeat(64),
  width: 16, height: 16, format: "PNG",
};
const run = {
  analysis_run_id: "run_test_only", asset_id: asset.asset_id,
  asset_sha256: asset.source_sha256, workspace_id: asset.workspace_id, project_id: asset.project_id,
  annotation_revision: 0, backend: "local-deterministic", backend_connected: true,
  execution_status: "COMPLETED", workflow_status: "AWAITING_HUMAN_REVIEW",
  events: [], knowledge_hits: [], tool_call_count: 1, model_call_count: 0,
  goal: "Duplicate test", intent: "Inspect duplicate evidence", document_sha256: "b".repeat(64),
  raw_images_transmitted: false,
  recommendation: { code: "DUPLICATE_REVIEW", severity: "HIGH", title: "Duplicate evidence",
    summary: "Two identical assets", next_action: "Review duplicate", evidence_refs: [], decision_authority: "none" },
  human_gate: { required_action: "Human review", status: "AWAITING_HUMAN_REVIEW", production_authority: "human_only" },
};

test("duplicate evidence without BBox offers the real snapshot handoff from overview", async () => {
  const page = await openScenario({ component: "agent", asset, run });
  try {
    const handoff = page.getByRole("button", { name: /冻结项目并交给 Agent/ });
    await page.getByRole("tab", { name: "概览", exact: true }).waitFor();
    assert.equal(await handoff.isVisible(), true);
    assert.equal(await handoff.isEnabled(), true);
    await handoff.click();
    assert.deepEqual(await page.evaluate(() => ({ handoff: window.__calls.handoff, create: window.__calls.create })), { handoff: 1, create: 0 });
  } finally { await page.close(); }
});

for (const [name, scenario] of [
  ["stale annotations", { traceStale: true }],
  ["mismatched asset SHA", { run: { ...run, asset_sha256: "c".repeat(64) } }],
  ["mismatched asset identity", { run: { ...run, asset_id: "asset_other" } }],
  ["mismatched workspace", { run: { ...run, workspace_id: "wsp_other" } }],
  ["mismatched project", { run: { ...run, project_id: "prj_other" } }],
]) {
  test(`duplicate handoff remains disabled for ${name}`, async () => {
    const page = await openScenario({ component: "agent", asset, run, ...scenario });
    try {
      const handoff = page.getByRole("button", { name: /冻结项目并交给 Agent/ });
      await page.getByRole("tab", { name: "概览", exact: true }).waitFor();
      assert.equal(await handoff.isVisible(), true);
      assert.equal(await handoff.isDisabled(), true);
      assert.equal(await page.evaluate(() => window.__calls.handoff), 0);
    } finally { await page.close(); }
  });
}
