/** Actual HTTP + actual React entrypoint + actual API + isolated temporary SQLite.
 * Only the desktop/browser startup-capability bootstrap is replaced with an in-memory fixture.
 * No business response mocks, real user database, model calls, training or credential files.
 */
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { createServer, request as proxyRequest } from "node:http";
import { once } from "node:events";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(root, "web");
const require = createRequire(path.join(webRoot, "package.json"));
const { build } = await import(pathToFileURL(require.resolve("vite")).href);
const react = (await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href)).default;
const cached = "D:/Users/living/.npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core/index.mjs";
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || (existsSync(cached) ? cached : require.resolve("playwright"))).href);
const capability = randomBytes(36).toString("base64url");
const password = randomBytes(24).toString("base64url");
let backend, backendPort, backendClosed, browser, shell, origin, bundle = "", css = "";
const requestLog = [];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

before(async () => {
  shell = createServer((req, res) => {
    if (req.url?.startsWith("/v1/")) {
      if (!backendPort) { res.writeHead(503); res.end(); return; }
      // Do not add X-Forwarded headers: setup deliberately requires a direct loopback peer.
      const upstream = proxyRequest({ host: "127.0.0.1", port: backendPort, path: req.url,
        method: req.method, headers: { ...req.headers, host: `127.0.0.1:${backendPort}` } }, (reply) => {
        requestLog.push({ method: req.method, path: req.url?.split("?", 1)[0], status: reply.statusCode });
        res.writeHead(reply.statusCode || 502, reply.headers); reply.pipe(res);
      });
      upstream.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
      req.pipe(upstream); return;
    }
    if (req.url === "/bundle.js") { res.writeHead(200, { "Content-Type": "text/javascript", "Cache-Control": "no-store" }); res.end(bundle); return; }
    if (req.url === "/bundle.css") { res.writeHead(200, { "Content-Type": "text/css", "Cache-Control": "no-store" }); res.end(css); return; }
    res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
    res.end("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><link rel='stylesheet' href='/bundle.css'></head><body><div id='root'></div><script src='/bundle.js'></script></body></html>");
  });
  shell.listen(0, "127.0.0.1"); await once(shell, "listening");
  origin = `http://127.0.0.1:${shell.address().port}`;
  const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("VISIONDATA_")));
  const python = process.env.VDG_TEST_PYTHON || path.join(root, ".venv/Scripts/python.exe");
  assert.ok(existsSync(python), "existing project Python is required; no dependencies are installed");
  backend = spawn(python, [path.join(root, "tests/helpers/identity_live_backend.py")], { cwd: root, windowsHide: true,
    env: { ...environment, PYTHONUTF8: "1", VISIONDATA_SESSION_TOKEN: capability, VISIONDATA_WEB_ORIGINS: origin }, stdio: ["pipe", "pipe", "pipe"] });
  backendClosed = once(backend, "exit");
  // Deliberately discard child stderr. Failures use generic test diagnostics, never request bodies.
  backend.stderr.resume();
  await new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("isolated API startup timed out")), 30000);
    backend.once("error", () => { clearTimeout(timer); reject(new Error("isolated Python process could not start")); });
    backend.once("exit", () => { if (!backendPort) { clearTimeout(timer); reject(new Error("isolated API exited before readiness")); } });
    backend.stdout.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      for (const line of buffer.split("\n").slice(0, -1)) {
        try { const parsed = JSON.parse(line); if (Number.isInteger(parsed.port)) { backendPort = parsed.port; clearTimeout(timer); resolve(); } } catch { /* metadata only */ }
      }
      buffer = buffer.slice(buffer.lastIndexOf("\n") + 1);
    });
  });
  for (let attempt = 0; attempt < 150; attempt += 1) {
    if ((await fetch(`${origin}/v1/health`).catch(() => null))?.ok) break;
    if (attempt === 149) throw new Error("isolated API health did not become ready");
    await wait(100);
  }
  const result = await build({ root: webRoot, configFile: false, envDir: false, logLevel: "error",
    define: { "process.env.NODE_ENV": JSON.stringify("production"), "import.meta.env.VITE_VISIONDATA_PUBLIC_REPLAY": JSON.stringify("false"), "import.meta.env.VITE_VISIONDATA_API_BASE_URL": JSON.stringify(""), "import.meta.env.VITE_VISIONDATA_REVIEWER_BASE_URL": JSON.stringify("") },
    build: { write: false, minify: false, lib: { entry: path.join(webRoot, "src/main.tsx"), name: "IdentityLive", formats: ["iife"] } },
    plugins: [react(), { name: "memory-only-startup-fixture", enforce: "pre",
      resolveId(id) { if (id.endsWith("/platform/browserSession")) return "\0identity-live-bootstrap"; },
      load(id) { if (id === "\0identity-live-bootstrap") return "export function resolveBrowserSessionBootstrap(){return {sessionToken:window.__identityLiveStartup};}"; },
    }],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = output.find((item) => item.type === "chunk").code;
  css = output.filter((item) => item.type === "asset" && item.fileName.endsWith(".css")).map((item) => item.source).join("\n");
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});

after(async () => {
  await browser?.close();
  if (backend && backend.exitCode === null) {
    backend.stdin.end("shutdown\n");
    const exited = await Promise.race([backendClosed.then(() => true), wait(10000).then(() => false)]);
    if (!exited) { backend.kill(); await backendClosed; throw new Error("isolated API needed forced shutdown; temporary-root cleanup is unverified"); }
  }
  if (shell) { shell.closeAllConnections(); await new Promise((resolve) => shell.close(resolve)); }
});

test("real HTTP setup, account management, workspace creation, platform/models routes, login/logout and denial", { timeout: 120000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(20000);
  await page.addInitScript((value) => { window.__identityLiveStartup = value; }, capability);
  try {
    await page.goto(`${origin}/account`);
    await page.getByRole("heading", { name: "创建首个管理员" }).waitFor();
    await page.getByLabel("登录名", { exact: true }).fill("http-smoke-admin");
    await page.getByLabel("显示名称").fill("HTTP 隔离测试管理员");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByLabel("再次输入密码").fill(password);
    await page.getByRole("button", { name: "创建管理员并登录" }).click();
    await page.getByTestId("identity-account-page").waitFor();
    await page.locator("#sessions").getByText("当前会话", { exact: true }).waitFor();
    assert.ok(requestLog.some((item) => item.path === "/v1/identity/setup" && item.status === 201));
    assert.ok(requestLog.some((item) => item.path === "/v1/identity/sessions" && item.status === 200));
    await page.getByLabel("新工作区名称", { exact: true }).fill("HTTP smoke owned workspace");
    const creationReply = page.waitForResponse((reply) => reply.url().endsWith("/v1/workspaces") && reply.request().method() === "POST" && reply.status() === 201);
    await page.getByRole("button", { name: "创建我的工作区", exact: true }).click();
    await page.locator("#create-workspace").getByText(/已确认新工作区/).waitFor();
    const createdWorkspace = await (await creationReply).json();
    assert.equal(createdWorkspace.owner_user_id, "usr_local_demo");
    await page.getByLabel("选择工作空间", { exact: true }).selectOption(createdWorkspace.workspace_id);
    assert.ok(requestLog.some((item) => item.path === "/v1/workspaces" && item.method === "POST" && item.status === 201));
    // Client-side navigation keeps the memory-only login session.
    await page.locator('.workbench-nav-group').filter({ hasText: '更多工具' }).locator('summary').click();
    await page.locator('a[href="/platform"]').first().click();
    await page.getByRole("heading", { name: "任务总览", exact: true }).waitFor();
    await page.getByRole("heading", { name: "请先选择工作空间和项目", exact: true }).waitFor();
    await page.locator('a[href="/models"]').first().click();
    await page.getByRole("heading", { name: "模型与 API 管理", exact: true }).waitFor();
    await page.getByRole("button", { name: "视觉模型与训练", exact: true }).click();
    await page.getByText("请登录并选择工作空间和项目；本页不使用匿名演示模型。", { exact: true }).waitFor();
    await page.locator('a[href="/data-pools"]').first().click();
    await page.getByRole("heading", { name: "数据池与返修版本", exact: true }).waitFor();
    await page.getByText("请先选择工作空间和项目。这里不会显示其他项目的数据池。", { exact: true }).waitFor();
    await page.locator('a[href="/learning"]').first().click();
    await page.getByRole("heading", { name: "数据处置与学习闭环", exact: true }).waitFor();
    await page.getByText("请先在左侧选择工作空间和项目。", { exact: true }).waitFor();
    assert.equal(requestLog.some((item) => item.method === "POST" && /train|download|inference|probe/.test(item.path || "")), false);
    await page.locator('a[href="/account"]').first().click();
    await page.getByTestId("identity-account-page").waitFor();
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    const denied = await page.evaluate(async () => (await fetch("/v1/workspaces")).status);
    assert.equal(denied, 401);
    await page.getByLabel("登录名", { exact: true }).fill("http-smoke-admin");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.getByTestId("identity-account-page").waitFor();
    assert.ok(requestLog.some((item) => item.path === "/v1/identity/login" && item.status === 200));
    assert.equal((await page.locator("body").innerText()).includes(password), false);
    const storage = await page.evaluate(() => [Object.keys(localStorage), Object.keys(sessionStorage)].flat());
    assert.ok(storage.every((key) => !/token|password|bearer|session/i.test(key)));
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
  } finally { await page.close(); }
});

test("real desktop workbench navigation, image upload, canvas annotation save and neutral surfaces", { timeout: 150000 }, async () => {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.setDefaultTimeout(18000);
  const shots=path.join(root,'output/playwright/workbench-redesign-live');mkdirSync(shots,{recursive:true});
  const interaction=[];const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const record=(action)=>interaction.push({at:new Date().toISOString(),action});
  await page.addInitScript(value=>{window.__identityLiveStartup=value;},capability);
  try {
    await page.goto(`${origin}/workspace`);
    await page.getByLabel('登录名',{exact:true}).fill('http-smoke-admin');
    await page.getByLabel('密码',{exact:true}).fill(password);
    await page.getByRole('button',{name:'登录',exact:true}).click();
    await page.locator('.linear-sidebar').waitFor();record('login using actual isolated account');
    assert.equal(await page.getByTestId('daily-navigation').locator('a').count(),5);
    assert.equal(await page.locator('html').getAttribute('data-accent'),'graphite');
    assert.equal(await page.locator('.linear-sidebar').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(27, 28, 31)');
    await page.getByRole('button',{name:'创建空项目',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'新建项目',exact:true});
    await dialog.getByLabel('项目名称',{exact:true}).fill('界面验收 · 隔离项目');
    await dialog.getByRole('button',{name:'创建空项目',exact:true}).click();
    await dialog.waitFor({state:'hidden'});record('created own isolated project from sidebar');
    await page.getByRole('button',{name:'导入图像',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'导入图像',exact:true}).isEnabled(),true);
    await page.screenshot({path:path.join(shots,'workbook-empty-1440.png')});
    const uploaded=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/assets')&&r.status()===201);
    await page.locator('.operator-workspace > input[type=file]').setInputFiles(path.join(root,'sample_data/clear/clean-val-gear.png'));
    await uploaded;record('uploaded actual generated fixture bytes through visible file input');
    const canvas=page.locator('canvas.inspection-canvas');await canvas.waitFor();
    await page.waitForFunction(()=>document.querySelector('canvas.inspection-canvas')?.getAttribute('aria-busy')==='false');
    await page.getByRole('button',{name:'框选',exact:true}).click();
    const box=await canvas.boundingBox();assert.ok(box&&box.width>150&&box.height>150);
    const d=Math.min(box.width,box.height)*.11;
    await page.mouse.move(box.x+box.width/2-d,box.y+box.height/2-d);await page.mouse.down();
    await page.mouse.move(box.x+box.width/2+d,box.y+box.height/2+d,{steps:10});await page.mouse.up();
    await page.getByLabel('标注类别',{exact:true}).fill('inspection-example');
    const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith('/annotations')&&r.status()===200);
    await page.getByRole('button',{name:/保存标注/}).click();await saved;record('drew canvas rectangle and saved actual annotation through API');
    await page.waitForFunction(()=>document.querySelector('.canvas-status')?.textContent?.includes('1 boxes'));
    await page.screenshot({path:path.join(shots,'workbook-annotated-1440.png')});
    await page.getByRole('button',{name:'剖面探针',exact:true}).click();
    await page.mouse.move(box.x+box.width/2-d,box.y+box.height/2);await page.mouse.down();
    await page.mouse.move(box.x+box.width/2+d,box.y+box.height/2,{steps:8});await page.mouse.up();
    await page.locator('.optical-probe').waitFor();record('pixel profile probe displays calculated curve');
    await page.screenshot({path:path.join(shots,'workbook-probe-1440.png')});
    await page.keyboard.press('Control+b');assert.equal(await page.locator('.linear-shell').evaluate(e=>e.classList.contains('is-sidebar-collapsed')),true);
    await page.keyboard.press('Control+b');record('keyboard toggled sidebar and returned');
    await page.keyboard.press('Control+k');await page.getByLabel('全局搜索',{exact:true}).fill('模型');
    await page.keyboard.press('Enter');await page.getByRole('heading',{name:'模型与 API 管理',exact:true}).waitFor();record('command palette searches and opens model page');
    await page.locator('[data-nav-path="/settings"]').click();
    await page.getByRole('heading',{name:'设置',exact:true}).waitFor();
    assert.equal(await page.locator('.provider-form').count(),0);
    await page.screenshot({path:path.join(shots,'settings-actual-http-1440.png'),fullPage:true});record('settings has one canonical model link and no duplicated editor');
    await page.locator('[data-nav-path="/integrations"]').click();
    await page.locator('.integration-controls').waitFor();
    await page.getByText('当前工作空间还没有授权来源。',{exact:true}).waitFor();
    await page.screenshot({path:path.join(shots,'integrations-actual-http-1440.png'),fullPage:true});record('opened actual source management surface');
    await page.locator('[data-nav-path="/workspace"]').click();await page.locator('canvas.inspection-canvas').waitFor();
    for(const width of [1280,1920]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      const panes=await page.locator('.operator-grid').evaluate(grid=>[...grid.querySelectorAll(':scope > .asset-browser, :scope > .operator-editor, :scope > .operator-inspector')].map(e=>{const r=e.getBoundingClientRect();return {right:r.right,left:r.left,width:r.width};}));
      assert.equal(panes.length,3);
      assert.ok(panes.every(p=>p.left>=0&&p.right<=width+1&&p.width>=220),'all three panes must fit; hidden outer overflow is not proof of fit');
      await page.screenshot({path:path.join(shots,`workbook-${width}.png`)});record(`desktop layout ${width}`);
    }
    assert.deepEqual(errors,[]);
    assert.equal(requestLog.some(r=>r.method==='POST'&&/training|download|probe/.test(r.path||'')),false);
  } finally {
    writeFileSync(path.join(shots,'interaction.json'),JSON.stringify({scope:'REAL_HTTP_REACT_WITH_ISOLATED_DATA',actions:interaction,pageErrors:errors},null,2),'utf8');
    await page.close();
  }
});
