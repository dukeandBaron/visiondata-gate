import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(repoRoot, "web");
const requireWeb = createRequire(path.join(webRoot, "package.json"));
const { build, transformWithOxc } = await import(pathToFileURL(requireWeb.resolve("vite")).href);
let browser;
let bundle;

const entry = `
  import {createRoot} from 'react-dom/client';
  import {MemoryRouter} from 'react-router-dom';
  import {TaskResponsibilityRail,CapaRequestReadbackRail,RunRecoveryRail} from '/src/components/FinalsTaskRails.tsx';
  function Harness(){
    if(window.__scenario==='responsibility') return <TaskResponsibilityRail items={[
      {id:'agent',label:'Agent 组织',state:'OBSERVED',summary:'3/5 Workers',detail:'按触发证据选择',href:'/command-center'},
      {id:'tool',label:'确定性工具',state:'OBSERVED',summary:'7 events',detail:'工具回执已落盘',href:'/runs'},
      {id:'human',label:'具名人员',state:'WAITING',summary:'等待终审',detail:'人工闸门未完成',href:'/command-center'},
      {id:'readback',label:'系统回读',state:'UNKNOWN',summary:'UNKNOWN',detail:'结果尚未回读',href:'/lineage'}
    ]}/>;
    if(window.__scenario==='capa') return <CapaRequestReadbackRail phase='REQUEST_UNKNOWN'/>;
    return <RunRecoveryRail state='HUMAN_REVIEW' title='等待具名人工终审' detail='规则已通过，但仍无生产放行权。' href='/command-center?task=task_test' actionLabel='打开人工终审'/>;
  }
  createRoot(document.getElementById('root')).render(<MemoryRouter><Harness/></MemoryRouter>);
`;

before(async () => {
  const result = await build({
    root: webRoot,
    configFile: false,
    logLevel: "error",
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: "/__goal2_finals_p0.tsx", name: "Goal2FinalsP0", formats: ["iife"] } },
    plugins: [{
      name: "goal2-finals-p0",
      enforce: "pre",
      resolveId(id) { if (id.endsWith("__goal2_finals_p0.tsx")) return "\0goal2-finals-p0.tsx"; },
      load(id) { if (id === "\0goal2-finals-p0.tsx") return entry; },
      transform(code, id) { if (id === "\0goal2-finals-p0.tsx") return transformWithOxc(code, id.slice(1), { lang: "tsx", jsx: { runtime: "automatic" } }); },
    }],
  });
  bundle = (Array.isArray(result) ? result[0] : result).output.find((item) => item.type === "chunk").code;
  const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || requireWeb.resolve("playwright")).href);
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || [
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
  ].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});

after(async () => { await browser?.close(); });

async function openScenario(scenario) {
  const page = await browser.newPage();
  await page.route("http://127.0.0.1:19894/**", (route) => route.fulfill({ contentType: "text/html", body: '<!doctype html><div id="root"></div>' }));
  await page.goto("http://127.0.0.1:19894/test");
  await page.evaluate((value) => { window.__scenario = value; }, scenario);
  await page.addScriptTag({ content: bundle });
  return page;
}

test("responsibility rail keeps missing readback UNKNOWN", async () => {
  const page = await openScenario("responsibility");
  try {
    assert.equal(await page.getByText("Agent 组织", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("确定性工具", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("具名人员", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("系统回读", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("UNKNOWN", { exact: true }).count(), 2);
  } finally { await page.close(); }
});

test("unknown CAPA write stops at request sent and permits GET reconciliation only", async () => {
  const page = await openScenario("capa");
  try {
    await page.getByText("REQUEST SENT / UNKNOWN", { exact: true }).waitFor();
    assert.equal(await page.getByText("不得自动重放写请求；只允许 GET 对账。", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("SERVER VERIFIED", { exact: true }).isVisible(), true);
    assert.equal(await page.locator(".capa-readback-rail .is-complete").count(), 1);
    assert.equal(await page.locator(".capa-readback-rail .is-current").count(), 1);
  } finally { await page.close(); }
});

test("human review recovery is pending authority rather than final pass", async () => {
  const page = await openScenario("recovery");
  try {
    await page.getByText("等待具名人工终审", { exact: true }).waitFor();
    assert.equal(await page.getByText("HUMAN REVIEW", { exact: true }).isVisible(), true);
    assert.equal(await page.getByText("PASS", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("link", { name: "打开人工终审" }).getAttribute("href"), "/command-center?task=task_test");
  } finally { await page.close(); }
});
