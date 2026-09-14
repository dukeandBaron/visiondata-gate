/** Real React identity forms and validators; all transport and accounts are synthetic. */
import assert from "node:assert/strict";
import { before, after, test } from "node:test";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(root, "web");
const require = createRequire(path.join(webRoot, "package.json"));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve("vite")).href);
const cached = "D:/Users/living/.npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core/index.mjs";
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || (existsSync(cached) ? cached : require.resolve("playwright"))).href);
let browser, bundle, css;
const admin = { user_id: "usr_test_admin", login_name: "test.admin", display_name: "测试管理员", email: null, platform_role: "ADMIN", status: "ACTIVE", created_at: "2026-09-12T01:00:00Z" };
const member = { ...admin, user_id: "usr_test_member", login_name: "test.member", display_name: "测试成员", platform_role: "USER" };
const pending = { ...member, status: "PENDING" };
const token = "synthetic-identity-bearer-never-real-0123456789012345";
const password = "  synthetic password  ";
const userSession = { session_id: "sess_synthetic", created_at: "2026-09-12T01:00:00Z", expires_at: "2099-09-12T09:00:00Z", revoked_at: null, is_current: true };
function tokenResponse(user = admin) { return { user, access_token: token, token_type: "Bearer", expires_at: "2099-09-12T09:00:00Z" }; }
function responses(setup = false) {
  return {
    "GET /v1/identity/status": { payload: { setup_required: setup, identity_required: !setup, registration_policy: "ADMIN_APPROVAL", authentication_mode: setup ? "SETUP_REQUIRED" : "USER_SESSION", startup_capability_required: true } },
    "POST /v1/identity/setup": { payload: tokenResponse(), status: 201 },
    "POST /v1/identity/login": { payload: tokenResponse() },
    "POST /v1/identity/register": { payload: pending, status: 201 },
    "GET /v1/identity/me": { payload: admin },
    "GET /v1/identity/sessions": { payload: { sessions: [userSession] } },
    "GET /v1/identity/admin/users": { payload: { users: [admin, pending] } },
    "GET /v1/identity/workspaces/wsp_test/members": { payload: { members: [{ user_id: admin.user_id, display_name: admin.display_name, role: "owner" }] } },
    "POST /v1/identity/logout": { status: 204 },
    "POST /v1/identity/password": { status: 204 },
    "DELETE /v1/identity/sessions/sess_synthetic": { status: 204 },
    "POST /v1/identity/admin/users/usr_test_member/approve": { payload: member },
    "PUT /v1/identity/admin/users/usr_test_member/status": { payload: { ...member, status: "DISABLED" } },
    "PUT /v1/identity/workspaces/wsp_test/members/usr_test_member": { payload: { members: [{ user_id: member.user_id, display_name: member.display_name, role: "member" }] } },
  };
}
const apiMock = `
  import {getIdentitySessionHeaders} from '/src/identitySession.ts';
  export class OperatorApiError extends Error {constructor(code,message,status){super(message);this.code=code;this.status=status;}}
  export async function operatorFetch(path,init={}) {
    const method=init.method||'GET';
    window.__calls.push({path,method,body:init.body?JSON.parse(init.body):null,headers:getIdentitySessionHeaders()});
    const fixture=window.__responses[method+' '+path];
    if(!fixture)throw new OperatorApiError('HTTP_404','Synthetic missing route',404);
    const make=()=>{if(fixture.error)throw new OperatorApiError('SYNTHETIC_FAILURE',fixture.message||'fixture failure',fixture.status||503);
      return new Response(fixture.status===204?null:JSON.stringify(fixture.payload),{status:fixture.status||200,headers:{'Content-Type':'application/json'}});};
    if(fixture.hold)return new Promise((resolve,reject)=>{window.__resolveHeld=()=>{try{resolve(make())}catch(e){reject(e)}}});
    return make();
  }
`;
const entry = `
  import {createRoot} from 'react-dom/client';
  import {IdentityProvider,useIdentity} from '/src/IdentityContext.tsx';
  import {IdentityAccessScreen} from '/src/components/IdentityAccessScreen.tsx';
  import {AccountPage} from '/src/pages/AccountPage.tsx';
  import * as session from '/src/identitySession.ts';
  import * as api from '/src/data/identityApi.ts';
  window.__identitySession=session; window.__identityApi=api;
  function Gate(){const identity=useIdentity();window.__phase=identity.status;
    return identity.status==='authenticated'?<AccountPage key={identity.user.user_id+':'+identity.generation}/>:<IdentityAccessScreen/>;}
  createRoot(document.getElementById('root')).render(<IdentityProvider><Gate/></IdentityProvider>);
`;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: "error",
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: "/__identity_test.tsx", name: "IdentityTest", formats: ["iife"] } },
    plugins: [{ name: "isolated-identity", enforce: "pre", resolveId(id) {
      if (id.endsWith("__identity_test.tsx")) return "\0identity-entry.tsx";
      if (id.endsWith("/ProductContext")) return "\0identity-product";
      if (id.endsWith("/data/api") || id === "./api") return "\0identity-api";
    }, load(id) {
      if (id === "\0identity-entry.tsx") return entry;
      if (id === "\0identity-product") return "export function useProduct(){return {...window.__product,refreshWorkspaceScope:async()=>{window.__refreshCount=(window.__refreshCount||0)+1;}};}";
      if (id === "\0identity-api") return apiMock;
    }, transform(code, id) { if (id === "\0identity-entry.tsx") return transformWithOxc(code, id.slice(1), { lang: "tsx", jsx: { runtime: "automatic" } }); } }],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = output.find((item) => item.type === "chunk").code;
  css = readFileSync(path.join(webRoot, "src/styles/tokens.css"), "utf8") + output.filter((item) => item.type === "asset" && item.fileName.endsWith(".css")).map((item) => item.source).join("\n");
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});
after(async () => { await browser?.close(); });
async function openPage(overrides = {}, setup = false, product = { activeWorkspace: { workspace_id: "wsp_test", name: "测试工作区", role: "owner" } }) {
  const page = await browser.newPage({ viewport: { width: 1365, height: 950 } });
  page.setDefaultTimeout(5_000);
  await page.route("http://identity.test/**", (route) => route.fulfill({ body: "<!doctype html><html><head></head><body><div id='root'></div></body></html>", contentType: "text/html" }));
  await page.goto("http://identity.test/");
  await page.evaluate(({ fixtures, product }) => { window.__responses = fixtures; window.__calls = []; window.__product = product; }, { fixtures: { ...responses(setup), ...overrides }, product });
  await page.addStyleTag({ content: `*{box-sizing:border-box}body{margin:0}.page-stack{padding:24px;display:grid;gap:18px}.panel{border:1px solid var(--line)}.panel-header{padding:18px;display:flex;justify-content:space-between}.panel-header h2{font-size:16px}.panel-header p{font-size:12px;color:var(--muted)}.detail-row{display:flex;justify-content:space-between;padding:9px 0;font-size:12px;gap:18px}.status-badge{font-size:11px}${css}` });
  await page.addScriptTag({ content: bundle });
  return page;
}
async function login(page) {
  await page.getByLabel("登录名", { exact: true }).fill("Test.Admin");
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByTestId("identity-account-page").waitFor();
}

test("login uses actual actor, retains password spaces and keeps bearer out of DOM and browser storage", async () => {
  const page = await openPage();
  try {
    await login(page);
    const result = await page.evaluate(() => ({ calls: window.__calls, actor: window.__identitySession.getIdentityActorId(), snapshot: window.__identitySession.getIdentitySessionSnapshot(), storage: [Object.keys(localStorage), Object.keys(sessionStorage)], text: document.body.innerText }));
    const call = result.calls.find((item) => item.path.endsWith("/login"));
    assert.deepEqual(call.body, { login_name: "test.admin", password });
    assert.equal(result.actor, admin.user_id);
    assert.equal(JSON.stringify(result.snapshot).includes(token), false);
    assert.equal(result.text.includes(token), false);
    assert.deepEqual(result.storage, [[], []]);
    assert.ok(result.calls.filter((item) => item.path.endsWith("/sessions")).every((item) => item.headers.Authorization === `Bearer ${token}`));
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.__identitySession.getIdentityActorId()), undefined);
    assert.equal(await page.getByTestId("identity-account-page").count(), 0);
  } finally { await page.close(); }
});

test("registration remains pending and never creates a bearer or business context", async () => {
  const page = await openPage();
  try {
    await page.getByRole("button", { name: "没有账户？提交注册申请" }).click();
    await page.getByLabel("登录名", { exact: true }).fill("test.member");
    await page.getByLabel("显示名称").fill("测试成员");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByLabel("再次输入密码").fill(password);
    await page.getByRole("button", { name: "提交注册申请", exact: true }).click();
    await page.getByText("注册申请已登记，当前状态为待管理员审批。尚未登录，也没有获得工作区权限。").waitFor();
    assert.equal(await page.getByTestId("identity-account-page").count(), 0);
    assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.path.endsWith("/sessions"))), false);
  } finally { await page.close(); }
});

test("unknown setup outcome is not retried; explicit status check determines the next screen", async () => {
  const page = await openPage({ "POST /v1/identity/setup": { error: true, status: 409 } }, true);
  try {
    await page.getByRole("heading", { name: "创建首个管理员" }).waitFor();
    await page.getByLabel("登录名", { exact: true }).fill("test.admin");
    await page.getByLabel("显示名称").fill("测试管理员");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByLabel("再次输入密码").fill(password);
    await page.getByRole("button", { name: "创建管理员并登录" }).click();
    await page.getByRole("heading", { name: "暂时无法确认账户状态" }).waitFor();
    assert.equal(await page.evaluate(() => window.__calls.filter((item) => item.path.endsWith("/setup")).length), 1);
    await page.evaluate((value) => { window.__responses["GET /v1/identity/status"] = value; }, responses()["GET /v1/identity/status"]);
    await page.getByRole("button", { name: "重新检查状态" }).click();
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.__calls.filter((item) => item.path.endsWith("/setup")).length), 1);
  } finally { await page.close(); }
});

test("wrong credentials are requested once and backend error text is never rendered", async () => {
  const page = await openPage({ "POST /v1/identity/login": { error: true, status: 401, message: "echoed-password-should-never-appear" } });
  try {
    await page.getByLabel("登录名", { exact: true }).fill("test.admin");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.getByRole("alert").waitFor();
    assert.equal((await page.locator("body").innerText()).includes("echoed-password-should-never-appear"), false);
    assert.equal(await page.getByLabel("密码", { exact: true }).inputValue(), "");
    assert.equal(await page.evaluate(() => window.__calls.filter((item) => item.path.endsWith("/login")).length), 1);
    assert.equal(await page.evaluate(() => window.__calls.filter((item) => item.path.endsWith("/status")).length), 1);
  } finally { await page.close(); }
});

test("unknown role, pending login and secret-bearing user responses fail closed", async () => {
  for (const user of [{ ...admin, platform_role: "SUPERADMIN" }, pending, { ...admin, password_hash: "not-a-real-secret" }]) {
    const page = await openPage({ "POST /v1/identity/login": { payload: tokenResponse(user) } });
    try {
      await page.getByLabel("登录名", { exact: true }).fill("test.admin");
      await page.getByLabel("密码", { exact: true }).fill(password);
      await page.getByRole("button", { name: "登录", exact: true }).click();
      await page.getByRole("alert").waitFor();
      assert.equal(await page.getByTestId("identity-account-page").count(), 0);
      assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
    } finally { await page.close(); }
  }
});

test("clearing an in-flight login session prevents a late response from restoring identity", async () => {
  const page = await openPage({ "POST /v1/identity/login": { payload: tokenResponse(), hold: true } });
  try {
    await page.getByLabel("登录名", { exact: true }).fill("test.admin");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.waitForFunction(() => Boolean(window.__resolveHeld));
    await page.evaluate(() => { window.__identitySession.clearIdentitySession(); window.__resolveHeld(); });
    await page.getByRole("button", { name: "登录", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
  } finally { await page.close(); }
});

test("admin approval and workspace grant are distinct confirmed actions", async () => {
  const page = await openPage();
  try {
    await login(page);
    await page.getByRole("button", { name: "批准注册", exact: true }).click();
    assert.equal(await page.evaluate(() => window.__calls.filter((item) => item.method === "POST" && item.path.endsWith("/approve")).length), 0);
    await page.evaluate((user) => { window.__responses["GET /v1/identity/admin/users"].payload.users[1] = user; }, member);
    await page.getByRole("button", { name: "确认批准注册" }).click();
    await page.waitForFunction(() => window.__calls.some((item) => item.path.endsWith("/approve")));
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.method === "PUT" && item.path.includes("/members/"))), false);
    await page.getByLabel("已启用账户的用户 ID").fill(member.user_id);
    await page.getByRole("button", { name: "添加成员", exact: true }).click();
    await page.evaluate((user) => { window.__responses["GET /v1/identity/workspaces/wsp_test/members"].payload.members.push({ user_id: user.user_id, display_name: user.display_name, role: "member" }); }, member);
    await page.getByRole("button", { name: "确认授权" }).click();
    await page.locator("#members").getByText("测试成员", { exact: true }).waitFor();
    const grant = await page.evaluate(() => window.__calls.find((item) => item.method === "PUT" && item.path.includes("/members/")));
    assert.deepEqual(grant.body, { role: "member" });
  } finally { await page.close(); }
});

test("ordinary members cannot render admin or workspace-owner management", async () => {
  const page = await openPage({ "POST /v1/identity/login": { payload: tokenResponse(member) } }, false, { activeWorkspace: { workspace_id: "wsp_test", name: "测试工作区", role: "member" } });
  try {
    await login(page);
    assert.equal(await page.getByRole("heading", { name: "用户管理", exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "添加成员", exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.path.endsWith("/admin/users") || item.path.endsWith("/members"))), false);
  } finally { await page.close(); }
});

test("password change preserves spaces and clears the prior user's complete UI context", async () => {
  const page = await openPage();
  try {
    await login(page);
    await page.getByLabel("当前密码", { exact: true }).fill(password);
    await page.getByLabel("新密码", { exact: true }).fill("  replacement password  ");
    await page.getByLabel("再次输入新密码").fill("  replacement password  ");
    await page.getByRole("button", { name: "修改密码并退出旧会话" }).click();
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    const call = await page.evaluate(() => window.__calls.find((item) => item.path.endsWith("/password")));
    assert.deepEqual(call.body, { current_password: password, new_password: "  replacement password  " });
    assert.equal(await page.getByTestId("identity-account-page").count(), 0);
    assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
  } finally { await page.close(); }
});

test("desktop login screen has no horizontal overflow and renders a deterministic screenshot", async () => {
  const page = await openPage();
  try {
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    const directory = path.join(root, "output/playwright/identity"); mkdirSync(directory, { recursive: true });
    await page.screenshot({ path: path.join(directory, "login-desktop.png"), fullPage: true });
    await login(page);
    await page.locator("#users").getByText("测试成员", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await page.screenshot({ path: path.join(directory, "account-desktop.png"), fullPage: true });
  } finally { await page.close(); }
});

test("unknown identity policy or inconsistent setup status never falls back to a login screen", async () => {
  const value = responses()["GET /v1/identity/status"].payload;
  for (const status of [{ ...value, registration_policy: "OPEN" }, { ...value, identity_required: false }, { ...value, startup_capability_required: false }]) {
    const page = await openPage({ "GET /v1/identity/status": { payload: status } });
    try {
      await page.getByRole("heading", { name: "暂时无法确认账户状态" }).waitFor();
      assert.equal(await page.getByRole("button", { name: "登录", exact: true }).count(), 0);
      assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
    } finally { await page.close(); }
  }
});

test("revoking the current session requires confirmation then removes account data", async () => {
  const page = await openPage();
  try {
    await login(page);
    await page.locator("#sessions").getByRole("button", { name: "撤销", exact: true }).click();
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.method === "DELETE")), false);
    await page.getByRole("button", { name: "确认撤销", exact: true }).click();
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
    assert.equal(await page.getByTestId("identity-account-page").count(), 0);
  } finally { await page.close(); }
});

test("a browser refresh cannot recover the previous bearer from persistent storage", async () => {
  const page = await openPage();
  try {
    await login(page);
    await page.reload();
    await page.evaluate((fixtures) => { window.__responses = fixtures; window.__calls = []; window.__product = {}; }, responses());
    await page.addScriptTag({ content: bundle });
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__identitySession.getIdentitySessionHeaders()), {});
    assert.equal(await page.getByTestId("identity-account-page").count(), 0);
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.path.endsWith("/sessions"))), false);
  } finally { await page.close(); }
});

test("account response validators reject duplicate sessions and unsupported member roles", async () => {
  const page = await openPage();
  try {
    await page.getByRole("heading", { name: "登录工作台", exact: true }).waitFor();
    const rejected = await page.evaluate(async ({ session, user }) => {
      window.__responses["GET /v1/identity/sessions"] = { payload: { sessions: [session, session] } };
      window.__responses["GET /v1/identity/workspaces/wsp_test/members"] = { payload: { members: [{ user_id: user.user_id, display_name: user.display_name, role: "viewer" }] } };
      const results = [];
      for (const read of [() => window.__identityApi.listIdentitySessions(), () => window.__identityApi.listIdentityWorkspaceMembers("wsp_test")]) {
        try { await read(); results.push(false); } catch (error) { results.push(error.code === "IDENTITY_CONTRACT_HOLD"); }
      }
      return results;
    }, { session: userSession, user: member });
    assert.deepEqual(rejected, [true, true]);
  } finally { await page.close(); }
});

test("own workspace creation uses authenticated owner and refreshes the existing scope", async () => {
  const page = await openPage({ "POST /v1/workspaces": { status: 201, payload: { workspace_id: "wsp_created", name: "My scope", owner_user_id: admin.user_id, role: "owner", created_at: admin.created_at } } });
  try {
    await login(page);
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.method === "POST" && item.path === "/v1/workspaces")), false);
    await page.getByLabel("新工作区名称", { exact: true }).fill("My scope");
    await page.getByRole("button", { name: "创建我的工作区", exact: true }).click();
    await page.locator("#create-workspace").getByText(/已确认新工作区/).waitFor();
    const call = await page.evaluate(() => window.__calls.find((item) => item.method === "POST" && item.path === "/v1/workspaces"));
    assert.deepEqual(call.body, { name: "My scope", owner_user_id: admin.user_id });
    assert.equal(await page.evaluate(() => window.__refreshCount), 1);
  } finally { await page.close(); }
});

test("unknown workspace creation locks submit and a list refresh cannot authorize resubmission", async () => {
  const page = await openPage({ "POST /v1/workspaces": { error: true, status: 503 } });
  try {
    await login(page);
    await page.getByLabel("新工作区名称", { exact: true }).fill("Uncertain scope");
    await page.getByRole("button", { name: "创建我的工作区", exact: true }).click();
    await page.locator("#create-workspace").getByText(/尚未确认创建结果，已锁定本次提交/).waitFor();
    assert.equal(await page.getByRole("button", { name: "创建我的工作区", exact: true }).isDisabled(), true);
    await page.getByRole("button", { name: "刷新工作区列表", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "创建我的工作区", exact: true }).isDisabled(), true);
    assert.equal(await page.evaluate(() => window.__calls.filter((item) => item.method === "POST" && item.path === "/v1/workspaces").length), 1);
  } finally { await page.close(); }
});
