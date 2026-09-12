/** Provider UI regression only: synthetic responses, never a real model request. */
import assert from "node:assert/strict";
import { before, after, test } from "node:test";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("..", import.meta.url));
const webRoot = path.join(root, "web");
const require = createRequire(path.join(webRoot, "package.json"));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve("vite")).href);
const cached = "D:/Users/living/.npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core/index.mjs";
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || (existsSync(cached) ? cached : require.resolve("playwright"))).href);
let browser, bundle;
const profile = { profile_id: "profile_test", workspace_id: "wsp_test", owner_user_id: "usr_test", display_name: "已保存的测试模型", provider_kind: "ollama_local", base_url: "http://127.0.0.1:11434", endpoint_host: "127.0.0.1:11434", model: "test-model", default_planner_mode: "shadow", is_default: false, secret_configured: false, last_test_status: "CONNECTED", config_sha256: "a".repeat(64), status: "ACTIVE" };
const connected = { schema_version: "visiondata-gate.provider-connection-test.v1", status: "CONNECTED", provider_kind: "ollama_local", endpoint_host: "127.0.0.1:11434", model: "test-model", reason_code: "CONNECTED", latency_ms: 1 };
const product = { activeWorkspace: { workspace_id: "wsp_test", name: "测试工作区" }, connection: { api: "CONNECTED" } };
const mock = `
  function call(name,input){window.__calls.push({name,input});const fixture=window.__fixtures[name];
    const result=()=>{if(fixture.error)throw new Error('synthetic transport unavailable');return structuredClone(fixture.value);};
    return fixture.hold?new Promise((resolve,reject)=>{window.__held[name]=()=>{try{resolve(result())}catch(e){reject(e)}}}):Promise.resolve().then(result);}
  export const listProviderProfiles=id=>call('list',id);
  export const testProviderConnection=input=>call('test',input);
  export const createProviderProfile=input=>call('create',input);
  export const testSavedProviderConnection=id=>call('saved-test',id);
  export const setDefaultProviderProfile=id=>call('default',id);
  export const revokeProviderProfile=id=>call('revoke',id);
`;
const entry = `import {useState} from 'react';import {createRoot} from 'react-dom/client';
  import {ProviderCenter} from '/src/components/ProviderCenter.tsx';
  function Harness(){const [product,setProduct]=useState(window.__product);window.__product=product;window.__setProduct=setProduct;
    return <ProviderCenter initialProvider={window.__initialProvider??undefined}/>;}
  createRoot(document.getElementById('root')).render(<Harness/>);`;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: "error", define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: "/__provider_test.tsx", name: "ProviderTest", formats: ["iife"] } },
    plugins: [{ name: "provider-isolation", enforce: "pre", resolveId(id) {
      if (id.endsWith("__provider_test.tsx")) return "\0provider-entry.tsx";
      if (id.endsWith("/ProductContext")) return "\0provider-product";
      if (id.endsWith("/data/api")) return "\0provider-api";
    }, load(id) {
      if (id === "\0provider-entry.tsx") return entry;
      if (id === "\0provider-product") return "export function useProduct(){return window.__product;}";
      if (id === "\0provider-api") return mock;
    }, transform(code, id) { if (id === "\0provider-entry.tsx") return transformWithOxc(code, id.slice(1), { lang: "tsx", jsx: { runtime: "automatic" } }); } }],
  });
  bundle = (Array.isArray(result) ? result[0] : result).output.find((item) => item.type === "chunk").code;
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});
after(async () => { await browser?.close(); });
async function openPage(overrides = {}, initialProvider = "ollama_local") {
  const page = await browser.newPage(); page.setDefaultTimeout(3000);
  await page.route("http://provider.test/**", (route) => route.fulfill({ body: "<div id='root'></div>", contentType: "text/html" }));
  await page.goto("http://provider.test/");
  await page.evaluate(({ fixtures, product, initialProvider }) => { window.__fixtures = fixtures; window.__product = product; window.__initialProvider = initialProvider; window.__calls = []; window.__held = {}; },
    { fixtures: { list: { value: [] }, test: { value: connected }, create: { value: profile }, "saved-test": { value: connected }, default: { value: profile }, revoke: { value: profile }, ...overrides }, product, initialProvider });
  await page.addScriptTag({ content: bundle });
  await page.getByRole("heading", { name: "Agent 语言模型接入" }).waitFor();
  return page;
}
const modelInput = (page) => page.locator('label').filter({ has: page.locator('span', { hasText: /^模型 ID$/ }) }).locator('input');
const baseInput = (page) => page.locator('input[type="url"]');
async function testConnection(page) {
  await page.getByRole("button", { name: "测试连接", exact: true }).click();
  await page.locator(".provider-test-result").getByText("CONNECTED", { exact: true }).first().waitFor();
}

test("failed list is unknown, not zero profiles; explicit retry only repeats GET", async () => {
  const page = await openPage({ list: { error: true } });
  try {
    await page.getByText("synthetic transport unavailable", { exact: true }).waitFor();
    assert.equal(await page.getByText("当前用户在此工作区还没有模型配置。", { exact: true }).count(), 0);
    await page.getByText(/配置清单未确认/).waitFor();
    await page.evaluate(() => { window.__fixtures.list = { value: [] }; });
    await page.getByRole("button", { name: "重新读取配置", exact: true }).click();
    await page.getByText("当前用户在此工作区还没有模型配置。", { exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__calls.map((item) => item.name)), ["list", "list"]);
  } finally { await page.close(); }
});

test("editing model clears a previously connected draft", async () => {
  const page = await openPage();
  try { await testConnection(page); await modelInput(page).fill("different-model"); assert.equal(await page.locator(".provider-test-result").count(), 0); assert.equal(await page.locator(".provider-feedback.is-success").count(), 0); }
  finally { await page.close(); }
});

test("Ollama loopback Base URL can use a custom port and editing clears its old result", async () => {
  const page = await openPage();
  try { assert.equal(await baseInput(page).isDisabled(), false); await testConnection(page); await baseInput(page).fill("http://127.0.0.1:12345"); assert.equal(await page.locator(".provider-test-result").count(), 0); await page.getByText(/Ollama.*回环/).waitFor(); }
  finally { await page.close(); }
});

test("API key edit clears the previous connected result and official host remains fixed", async () => {
  const page = await openPage({}, "openai");
  try { assert.equal(await baseInput(page).isDisabled(), true); await page.locator('input[type="password"]').fill("synthetic-key-before"); await testConnection(page); await page.locator('input[type="password"]').fill("synthetic-key-after"); assert.equal(await page.locator(".provider-test-result").count(), 0); }
  finally { await page.close(); }
});

test("offline transition clears old CONNECTED draft evidence and saved profile state", async () => {
  const page = await openPage({ list: { value: [profile] } });
  try { await testConnection(page); await page.evaluate(() => window.__setProduct({ ...window.__product, connection: { api: "UNAVAILABLE" } })); await page.getByRole("button", { name: "测试连接", exact: true }).isDisabled();
    await page.waitForFunction(() => document.querySelector('.provider-form__actions button').disabled);
    assert.equal(await page.getByText("CONNECTED", { exact: true }).count(), 0);
    assert.equal(await page.getByText("当前用户在此工作区还没有模型配置。", { exact: true }).count(), 0);
  } finally { await page.close(); }
});

test("a list response arriving after disconnect cannot restore CONNECTED state", async () => {
  const page = await openPage({ list: { value: [profile], hold: true } });
  try { await page.waitForFunction(() => Boolean(window.__held.list)); await page.evaluate(() => window.__setProduct({ ...window.__product, connection: { api: "UNAVAILABLE" } }));
    await page.waitForFunction(() => document.querySelector('.provider-form__actions button').disabled);
    await page.evaluate(async () => { window.__held.list(); await new Promise(requestAnimationFrame); });
    assert.equal(await page.getByText("CONNECTED", { exact: true }).count(), 0);
  } finally { await page.close(); }
});

test("a draft test resolving after disconnect cannot save a profile", async () => {
  const page = await openPage({ test: { value: connected, hold: true } });
  try { await page.getByRole("button", { name: "测试并安全保存", exact: true }).click(); await page.waitForFunction(() => Boolean(window.__held.test));
    await page.evaluate(() => window.__setProduct({ ...window.__product, connection: { api: "UNAVAILABLE" } }));
    await page.waitForFunction(() => window.__product.connection.api === "UNAVAILABLE"); await page.evaluate(() => window.__held.test());
    await page.waitForFunction(() => !document.querySelector('.provider-form select').disabled);
    assert.equal(await page.evaluate(() => window.__calls.some((item) => item.name === "create")), false);
    assert.equal(await page.getByText("CONNECTED", { exact: true }).count(), 0);
  } finally { await page.close(); }
});

test("new failed test cannot retain an earlier CONNECTED result", async () => {
  const page = await openPage();
  try { await testConnection(page); await page.evaluate(() => { window.__fixtures.test = { error: true }; }); await page.getByRole("button", { name: "测试连接", exact: true }).click(); await page.getByText("synthetic transport unavailable", { exact: true }).waitFor(); assert.equal(await page.getByText("CONNECTED", { exact: true }).count(), 0); }
  finally { await page.close(); }
});

test("provider defaults remain unchanged and boundary describes real local user sessions", async () => {
  const page = await openPage({}, null);
  try {
    // Passing undefined exercises the existing default prop, not a newly chosen provider.
    assert.equal(await page.locator('select').nth(0).inputValue(), "deepseek");
    assert.equal(await page.locator('select').nth(1).inputValue(), "shadow");
    assert.equal(await page.locator('input[type="checkbox"]').isChecked(), false);
    await page.getByText(/Bearer.*本地|本地.*Bearer/).waitFor();
    assert.equal(await page.getByText(/Actor Header 仍是本机原型身份/).count(), 0);
  } finally { await page.close(); }
});
