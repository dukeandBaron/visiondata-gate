/** Actual React interaction with synthetic transport. No private data, model calls or writes. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(root, "web");
const requireWeb = createRequire(path.join(webRoot, "package.json"));
const { build, transformWithOxc } = await import(pathToFileURL(requireWeb.resolve("vite")).href);
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || requireWeb.resolve("playwright")).href);
const workspace = { workspace_id: "wsp_start_test", name: "隔离交互测试工作空间" };
const projects = [
  { project_id: "prj_gears", workspace_id: workspace.workspace_id, name: "齿轮返修 · 测试项目", description: "验证标注修订与复核", source_kind: "local_authorized_directory" },
  { project_id: "prj_solder", workspace_id: workspace.workspace_id, name: "焊点复核 · 测试项目", description: "检查第二批图像", source_kind: "local_authorized_directory" },
];
const product = { connection: { api: "CONNECTED" }, activeWorkspace: workspace, activeProject: projects[0], projects,
  workspaceLoading: false, connectionRefreshing: false };
function task(id = "task_gears", projectId = "prj_gears", override = {}) {
  return { task_id: id, project_id: projectId, workspace_id: workspace.workspace_id,
    goal: "Review gear annotation", execution_status: "PLANNED", plan_approval_required: true, final_decision: null, ...override };
}
const scope = { workspace_id: workspace.workspace_id, project_id: "prj_gears" };
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",")}}`;
  return JSON.stringify(value);
}
function signed(value, header) {
  const receipt_sha256 = createHash("sha256").update(canonical(value) + "\n").digest("hex");
  return { payload: { ...value, receipt_sha256 }, headers: { [header]: receipt_sha256, ETag: `"${receipt_sha256}"` } };
}
const overviewPath = `/v1/workspaces/${scope.workspace_id}/agent-platform?project_id=${scope.project_id}`;
function overview() {
  return signed({ schema_version: "visiondata-gate.agent-platform.v1", ...scope,
    scope: { mode: "LOCAL_WORKSPACE", production_authentication: false }, capabilities: [],
    providers: { configured_count: 1, enabled_count: 1, connection_status: "NOT_PROBED" },
    tasks: [
      { task_id: "task_gears", goal: "Review gear annotation", execution_status: "PLANNED", final_decision: null, updated_at: "2026-09-13T00:00:00Z" },
      { task_id: "task_failed", goal: "Check failed image", execution_status: "FAILED", final_decision: "HOLD", updated_at: "2026-09-13T00:00:00Z" },
    ], task_count: 2, task_limit: 200, tasks_truncated: false }, "X-Agent-Platform-SHA256");
}
const mock = `
  export class OperatorApiError extends Error { constructor(code,message,status){super(message);this.code=code;this.status=status;} }
  function read(name, workspaceId, projectId) {
    const key=name+':'+projectId; const fixture=window.__fixtures[key]??{value:[]}; window.__calls.push({name,workspaceId,projectId,method:'GET'});
    const result=()=>{if(fixture.error)throw new Error('Synthetic read failure');return structuredClone(fixture.value);};
    return fixture.hold?new Promise((resolve,reject)=>{window.__held[key]=()=>{try{resolve(result())}catch(error){reject(error)}}}):Promise.resolve().then(result);
  }
  export const listOperatorImages=(w,p)=>read('images',w,p);
  export const listAgentTasks=(w,p)=>read('tasks',w,p);
  export const listOperatorWorkOrders=(w,p)=>read('orders',w,p);
  export async function operatorFetch(path,init={}){
    const method=init.method||'GET';window.__calls.push({path,method});const fixture=window.__responses[method+' '+path];
    if(!fixture||fixture.error)throw new OperatorApiError('HTTP_502','Synthetic transport unavailable',502);
    const result=()=>new Response(JSON.stringify(fixture.payload),{headers:fixture.headers});
    return fixture.hold?new Promise(resolve=>{window.__held[path]=()=>resolve(result())}):result();
  }
`;
const entry = `
  import {useState} from 'react';import {createRoot} from 'react-dom/client';
  import {MemoryRouter,Routes,Route,useLocation} from 'react-router-dom';
  import {HomePage} from '/src/pages/HomePage.tsx';import {AgentPlatformPage} from '/src/pages/AgentPlatformPage.tsx';
  import {initializeInterfacePreferences} from '/src/interfacePreferences.ts';initializeInterfacePreferences();
  import * as identity from '/src/identitySession.ts';window.__identity=identity;
  function Screen(){const location=useLocation();window.__location=location;return <Routes><Route path='/' element={<HomePage/>}/><Route path='/platform' element={<AgentPlatformPage/>}/><Route path='*' element={<h1>destination {location.pathname}</h1>}/></Routes>}
  function Harness(){const [product,setProduct]=useState(window.__product);window.__product=product;window.__setProduct=setProduct;
    window.__product.selectProject=(id)=>{const project=product.projects.find(p=>p.project_id===id);if(!project)return false;setProduct({...product,activeProject:project});return true;};
    window.__product.refreshWorkspaceScope=async()=>{window.__refreshScope=(window.__refreshScope||0)+1;};
    window.__product.refreshConnection=async()=>{window.__refreshConnection=(window.__refreshConnection||0)+1;};
    return <MemoryRouter initialEntries={[window.__route]}><Screen/></MemoryRouter>;}
  createRoot(document.getElementById('root')).render(<Harness/>);
`;
let browser, bundle, css;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: "error", define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: "/__start_test.tsx", name: "StartSurfacesTest", formats: ["iife"] } },
    plugins: [{ name: "isolated-start-surfaces", enforce: "pre", resolveId(id) {
      if (id.endsWith("__start_test.tsx")) return "\0start-entry.tsx";
      if (id.endsWith("/ProductContext")) return "\0start-context";
      if (id.endsWith("/data/api") || id === "./api") return "\0start-api";
    }, load(id) {
      if (id === "\0start-entry.tsx") return entry;
      if (id === "\0start-context") return "export function useProduct(){return window.__product;}";
      if (id === "\0start-api") return mock;
    }, transform(code,id) { if(id === "\0start-entry.tsx") return transformWithOxc(code,id.slice(1),{lang:"tsx",jsx:{runtime:"automatic"}}); } }],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = output.find(item => item.type === "chunk").code;
  css = ["tokens.css", "index.css", "workbench-interface.css"].map(file => readFileSync(path.join(webRoot,"src/styles",file),"utf8")).join("\n")
    + output.filter(item => item.type === "asset" && item.fileName.endsWith(".css")).map(item => item.source).join("\n");
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
  browser = await chromium.launch({headless:true,...(executablePath ? {executablePath} : {})});
});
after(async () => { await browser?.close(); });
async function openPage(options = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.setDefaultTimeout(8000);
  await page.route("http://127.0.0.1:19892/**",route => route.fulfill({contentType:"text/html",body:'<!doctype html><html lang="zh-CN"><body><div id="root"></div></body></html>'}));
  await page.goto("http://127.0.0.1:19892/test");
  await page.evaluate(({options,product,overviewPath,overviewValue}) => {window.__product=options.product??product;window.__route=options.route??'/';window.__calls=[];window.__held={};window.__fixtures=options.fixtures??{};window.__responses={['GET '+overviewPath]:overviewValue,...options.responses};}, {options,product,overviewPath,overviewValue:overview()});
  await page.addStyleTag({content:css});
  await page.addScriptTag({content:bundle});
  return page;
}
async function settled(page) { await page.waitForFunction(() => document.querySelector('#proof')?.getAttribute('aria-busy') === 'false'); }

test("home searches real project list, changes scope, and continues the selected workbook", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{value:[task()]}}});
  try {
    await page.getByRole('link',{name:/Review gear annotation/}).waitFor();
    await page.getByRole('searchbox',{name:'搜索项目'}).fill('焊点');
    assert.equal(await page.getByRole('button',{name:'选择项目 齿轮返修 · 测试项目'}).count(),0);
    await page.getByRole('button',{name:'选择项目 焊点复核 · 测试项目'}).click();
    await page.getByRole('heading',{name:'焊点复核 · 测试项目'}).waitFor();
    await settled(page);
    assert.equal(await page.getByRole('link',{name:/Review gear annotation/}).count(),0);
    assert.equal(await page.getByRole('button',{name:'选择项目 焊点复核 · 测试项目'}).getAttribute('aria-pressed'),'true');
    await page.getByRole('button',{name:'进入图像工作簿'}).click();
    await page.getByRole('heading',{name:'destination /workspace'}).waitFor();
    assert.equal(await page.evaluate(()=>window.__product.activeProject.project_id),'prj_solder');
    assert.equal(await page.evaluate(()=>window.__calls.some(call=>call.method !== 'GET')),false);
  } finally { await page.close(); }
});

test("empty state has a real create-project destination, not simulated assets", async () => {
  const page = await openPage({product:{...product,projects:[],activeProject:undefined}});
  try {
    await page.getByText('还没有工作项目',{exact:true}).waitFor();
    assert.equal(await page.getByRole('link',{name:'前往工作簿创建项目'}).getAttribute('href'),'/workspace');
    assert.equal(await page.getByRole('button',{name:'进入图像工作簿'}).isDisabled(),true);
    assert.equal(await page.locator('.start-counts dd').allTextContents().then(values=>values.every(value=>value==='未知')),true);
    assert.equal(await page.evaluate(()=>window.__calls.length),0);
    assert.equal(await page.locator('.home-stage-canvas,.home-frame-workbook,.home-stage-trace').count(),0);
    assert.equal(await page.getByText(/Raw outbound|LIVE CONTEXT|原图外发始终为 0/).count(),0);
  } finally { await page.close(); }
});

test("partial read failure stays unknown and explicit refresh replaces it with returned facts", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{error:true}}});
  try {
    await page.getByRole('alert').filter({hasText:'任务读取失败'}).waitFor();
    assert.deepEqual(await page.locator('.start-counts dd').allTextContents(),['0','未知','0']);
    await page.evaluate(()=>{window.__fixtures['tasks:prj_gears']={value:[]};});
    await page.getByRole('button',{name:'刷新当前项目待办'}).click();
    await settled(page);
    assert.deepEqual(await page.locator('.start-counts dd').allTextContents(),['0','0','0']);
    assert.equal(await page.getByRole('alert').count(),0);
  } finally { await page.close(); }
});

test("wrong-scope records are rejected rather than counted in the active project", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{value:[task('task_other','prj_other')]}}});
  try {
    await page.getByRole('alert').filter({hasText:'任务读取失败'}).waitFor();
    assert.equal(await page.getByRole('link',{name:/Review gear annotation/}).count(),0);
    assert.equal(await page.locator('.start-counts dd').nth(1).innerText(),'未知');
  } finally { await page.close(); }
});

test("late response from previous project never overwrites a new project", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{value:[task()],hold:true}}});
  try {
    await page.waitForFunction(()=>typeof window.__held['tasks:prj_gears']==='function');
    await page.getByRole('button',{name:'选择项目 焊点复核 · 测试项目'}).click();
    await settled(page);
    await page.evaluate(()=>window.__held['tasks:prj_gears']());
    await page.waitForTimeout(40);
    assert.equal(await page.getByRole('link',{name:/Review gear annotation/}).count(),0);
    assert.deepEqual(await page.locator('.start-counts dd').allTextContents(),['0','0','0']);
  } finally { await page.close(); }
});

test("identity generation invalidates a held read even if project id stays unchanged", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{value:[task()],hold:true}}});
  try {
    await page.waitForFunction(()=>typeof window.__held['tasks:prj_gears']==='function');
    await page.evaluate(()=>{window.__oldResolve=window.__held['tasks:prj_gears'];window.__fixtures['tasks:prj_gears']={value:[]};window.__identity.clearIdentitySession();});
    await settled(page);
    await page.evaluate(()=>window.__oldResolve());
    await page.waitForTimeout(40);
    assert.equal(await page.getByRole('link',{name:/Review gear annotation/}).count(),0);
  } finally { await page.close(); }
});

test("disconnect hides prior activity and permits an explicit connection check", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{value:[task()]}}});
  try {
    await page.getByRole('link',{name:/Review gear annotation/}).waitFor();
    await page.evaluate(()=>window.__setProduct({...window.__product,connection:{api:'UNAVAILABLE'}}));
    await page.getByText('连接后读取你的项目',{exact:true}).waitFor();
    assert.equal(await page.getByRole('link',{name:/Review gear annotation/}).count(),0);
    assert.deepEqual(await page.locator('.start-counts dd').allTextContents(),['未知','未知','未知']);
    await page.getByRole('button',{name:'重新检查连接'}).click();
    assert.equal(await page.evaluate(()=>window.__refreshConnection),1);
  } finally { await page.close(); }
});

test("project-list transport failure is not presented as an empty workspace", async () => {
  const page = await openPage({product:{...product,workspaceError:'Synthetic HTTP error'}});
  try {
    await page.getByText('项目列表读取失败',{exact:true}).waitFor();
    assert.equal(await page.getByText('还没有工作项目',{exact:true}).count(),0);
    assert.equal(await page.evaluate(()=>window.__calls.length),0);
    await page.getByRole('button',{name:'重新读取项目'}).click();
    assert.equal(await page.evaluate(()=>window.__refreshScope),1);
  } finally { await page.close(); }
});

test("task list search, status filtering and selection are actual controls and preserve query context", async () => {
  const page = await openPage({route:'/platform?view=working'});
  try {
    await page.getByText('当前项目回执已核验',{exact:true}).waitFor();
    await page.getByRole('searchbox',{name:'搜索当前项目任务'}).fill('failed');
    assert.equal(await page.locator('.agent-platform-task-list > button').count(),1);
    await page.getByRole('combobox',{name:'任务状态筛选'}).selectOption('active');
    await page.getByRole('status').filter({hasText:'没有匹配的任务'}).waitFor();
    await page.getByRole('combobox',{name:'任务状态筛选'}).selectOption('failed');
    await page.getByRole('button',{name:/Check failed image/}).click();
    await page.getByRole('link',{name:'打开任务与人工审批'}).waitFor();
    assert.match(await page.evaluate(()=>window.__location.search),/view=working/);
    assert.match(await page.evaluate(()=>window.__location.search),/task=task_failed/);
    assert.equal(await page.getByRole('link',{name:'打开任务与人工审批'}).getAttribute('href'),'/command-center?task=task_failed');
    await page.getByRole('alert').filter({hasText:'用量 UNKNOWN'}).waitFor();
    assert.equal(await page.evaluate(()=>window.__calls.some(call=>call.method!=='GET')),false);
  } finally { await page.close(); }
});

test("workflow defaults to a short disclosure, with canonical destinations after opening", async () => {
  const page = await openPage({route:'/platform'});
  try {
    const workflow=page.getByRole('region',{name:'视觉数据与模型工作流'});
    assert.equal(await workflow.locator('details').getAttribute('open'),null);
    await workflow.getByText('第一次使用？查看数据到模型的操作顺序',{exact:true}).click();
    assert.equal(await workflow.getByRole('link',{name:'选择起始模型'}).getAttribute('href'),'/models');
    assert.equal(await workflow.getByRole('link',{name:'训练、评测与回流'}).getAttribute('href'),'/models?tab=vision');
    assert.equal(await workflow.getByRole('link',{name:'CPU 参考学习闭环'}).getAttribute('href'),'/learning');
  } finally { await page.close(); }
});

test("platform offline transition prevents held verified data from returning", async () => {
  const page = await openPage({route:'/platform',responses:{['GET '+overviewPath]:{...overview(),hold:true}}});
  try {
    await page.waitForFunction((key)=>typeof window.__held[key]==='function',overviewPath);
    await page.evaluate(()=>window.__setProduct({...window.__product,connection:{api:'UNAVAILABLE'}}));
    await page.getByRole('alert').filter({hasText:'工作台 API 未连接'}).waitFor();
    await page.evaluate((key)=>window.__held[key](),overviewPath);
    await page.waitForTimeout(40);
    assert.equal(await page.getByText('当前项目回执已核验',{exact:true}).count(),0);
    assert.equal(await page.locator('.agent-platform-task-list').count(),0);
  } finally { await page.close(); }
});

test("desktop start surface fits 1280, 1440 and 1920 widths and captures the synthetic UI", async () => {
  const page = await openPage({fixtures:{"tasks:prj_gears":{value:[task()]}}});
  try {
    await page.getByRole('link',{name:/Review gear annotation/}).waitFor();
    for(const width of [1280,1440,1920]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.getByRole('searchbox',{name:'搜索项目'}).focus();
    assert.equal(await page.getByRole('searchbox',{name:'搜索项目'}).evaluate(element=>element===document.activeElement),true);
    const dir=path.join(root,'output/playwright/start-surfaces');mkdirSync(dir,{recursive:true});
    await page.screenshot({path:path.join(dir,'home-synthetic-desktop.png'),fullPage:true});
    await page.getByRole('link',{name:'任务总览',exact:true}).click();
    await page.getByText('当前项目回执已核验',{exact:true}).waitFor();
    await page.screenshot({path:path.join(dir,'platform-synthetic-desktop.png'),fullPage:true});
  } finally { await page.close(); }
});
