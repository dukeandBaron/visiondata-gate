/** Real React controls; synthetic API/desktop transport, never a customer source or model request. */
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
const product = { activeWorkspace: { workspace_id: "wsp_test", name: "测试工作空间" }, connection: { api: "CONNECTED", reviewer: "FALLBACK" } };
const user = { user_id: "usr_synthetic_reviewer", login_name: "reviewer.test", display_name: "测试复核员", email: null, created_at: "2026-09-13T00:00:00Z", platform_role: "USER", status: "ACTIVE" };
const runtime = { apiBaseUrl: "http://127.0.0.1:1", sessionToken: "synthetic-never-in-dom", dataRoot: "C:/Synthetic/data", configFile: "C:/Synthetic/config.env", sampleDataRoot: "C:/Synthetic/samples" };
const source = { source_id: 'src_test', display_name: '合成受控发布目录', adapter_kind: 'omni_ad_30_release', status: 'active', source_archive_sha256: 'a'.repeat(64), latest_authorization_event_sha256:'b'.repeat(64), authorization_event_count:1, created_at:'2026-09-13T00:00:00Z' };
const mock = `function call(name,input){window.__calls.push({name,input});const f=window.__fixtures[name]??{value:[]};const result=()=>{if(f.error)throw new Error('synthetic unavailable');return structuredClone(f.value);};return f.hold?new Promise((resolve,reject)=>{window.__held[name]=()=>{try{resolve(result())}catch(e){reject(e)}}}):Promise.resolve().then(result);}
 export const listLocalTaskSources=id=>call('sources',id);export const getAgentRuntimeCapabilities=()=>call('capabilities');export const getHostedAgentTeamsHealthStatus=()=>call('hosted-health');export const listSourceAuthorizationEvents=id=>call('events',id);export const authorizeLocalTaskSource=input=>call('authorize',input);export const revokeLocalTaskSource=input=>call('revoke',input);export const probeHostedAgentTeams=id=>call('probe',id);export const operatorActorUserId='legacy_actor_header';
 export const getPlatformCapability=()=>window.__platform;export const resolveDesktopRuntimeConfig=()=>call('desktop');export const openDesktopConfigDirectory=()=>call('open-directory');`;
const entry = `import {useState} from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter,Routes,Route,useLocation} from 'react-router-dom';
 import {SettingsPage} from '/src/pages/SettingsPage.tsx';import {IntegrationsPage} from '/src/pages/IntegrationsPage.tsx';import * as session from '/src/identitySession.ts';import {initializeInterfacePreferences} from '/src/interfacePreferences.ts';
 initializeInterfacePreferences();
 window.__identity=session;if(window.__user)session.setIdentitySession(window.__user,'synthetic-bearer-never-real-0123456789012345');
 function Screen(){const location=useLocation();window.__location=location;return <Routes><Route path='/settings' element={<SettingsPage/>}/><Route path='/integrations' element={<IntegrationsPage/>}/><Route path='*' element={<h1>destination {location.pathname}</h1>}/></Routes>}
 function Harness(){const [product,setProduct]=useState(window.__product);window.__product=product;window.__setProduct=setProduct;return <MemoryRouter initialEntries={[window.__route]}><Screen/></MemoryRouter>};createRoot(document.getElementById('root')).render(<Harness/>);`;
let browser, bundle, css;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: "error", define: { "process.env.NODE_ENV": JSON.stringify("production") }, build: { write: false, minify: false, lib: { entry: "/__control_test.tsx", name: "ControlTest", formats: ["iife"] } },
    plugins: [{ name: "isolated-control-surfaces", enforce: "pre", resolveId(id) {
      if (id.endsWith("__control_test.tsx")) return "\0control-entry.tsx";
      if (id.endsWith("/ProductContext")) return "\0control-product";
      if (id.endsWith("/data/api")) return "\0control-api";
      if (id === '@tauri-apps/api/core') return '\0control-tauri';
      if (id.endsWith("/components/ProviderCenter")) return "\0provider-sentinel";
    }, load(id) {
      if (id === "\0control-entry.tsx") return entry;
      if (id === "\0control-product") return "export function useProduct(){return window.__product;}";
      if (id === "\0control-api") return mock;
      if (id === '\0control-tauri') return mock + "export const invoke=command=>command==='desktop_runtime_config'?call('desktop'):call('open-directory');";
      if (id === "\0provider-sentinel") return "import {createElement} from 'react';export function ProviderCenter(){return createElement('div',{'data-testid':'duplicate-provider'},'Duplicate provider form')}";
    }, transform(code, id) { if (id === "\0control-entry.tsx") return transformWithOxc(code, id.slice(1), { lang: "tsx", jsx: { runtime: "automatic" } }); } }],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = output.find(item => item.type === "chunk").code;
  css = ['tokens.css','index.css','workbench-interface.css'].map(name=>readFileSync(path.join(webRoot, 'src/styles',name),'utf8')).join('\n') + output.filter(item => item.type === "asset" && item.fileName.endsWith(".css")).map(item => item.source).join("\n");
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});
after(async () => { await browser?.close(); });
async function openPage(route = "/settings", fixtures = {}, options = {}) {
  const page = await browser.newPage({ viewport: { width: options.width ?? 1440, height: 1000 } }); page.setDefaultTimeout(3000);
  await page.route("http://control.test/**", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><html lang='zh'><body><div id='root'></div></body></html>" }));
  await page.goto("http://control.test/");
  await page.evaluate(({ route, fixtures, options, product, user, runtime }) => {
    window.__route=route;window.__calls=[];window.__held={};window.__product=product;window.__user=options.anonymous?null:user;
    window.__platform={runtime:options.desktop?'TAURI':'BROWSER',platform:'WINDOWS',desktopPackaging:options.desktop?'AVAILABLE':'NOT_BUNDLED'};
    if(options.desktop)window.__TAURI_INTERNALS__={};
    window.__fixtures={sources:{value:[]},capabilities:{value:{model_profiles:[]}},'hosted-health':{value:'NOT_CONFIGURED'},desktop:{value:options.desktop?runtime:undefined},'open-directory':{value:undefined},...fixtures};
  }, { route, fixtures, options, product, user, runtime });
  await page.addStyleTag({ content: `*{box-sizing:border-box}body{margin:0;padding:32px;background:#17181a;color:#ededea;font-family:'Segoe UI',sans-serif}button,input,textarea,select{font:inherit}a{color:inherit}${css}` });
  await page.addScriptTag({ content: bundle });
  await page.getByRole("heading", { level: 1 }).waitFor();
  return page;
}

test("settings has one canonical model destination, no duplicate provider editor", async () => {
  const page=await openPage('/settings#providers');try {
    assert.equal(await page.getByTestId('duplicate-provider').count(),0);
    await page.getByRole('link',{name:'管理模型与 API',exact:true}).click();
    await page.getByRole('heading',{name:'destination /models',exact:true}).waitFor();
  } finally {await page.close();}
});
test("settings shows real account identity, not legacy actor header", async () => {
  const page=await openPage();try {
    await page.getByText(user.user_id,{exact:true}).waitFor();
    assert.equal(await page.getByText('LOCAL ACTOR HEADER',{exact:true}).count(),0);
    await page.getByText('企业 SSO / MFA：未验证',{exact:true}).waitFor();
  } finally {await page.close();}
});
test("settings density and motion respond immediately", async () => {
  const page=await openPage();try {
    await page.getByRole('button',{name:'紧凑',exact:true}).click();
    assert.equal(await page.getByRole('button',{name:'紧凑',exact:true}).getAttribute('aria-pressed'),'true');
    await page.getByLabel('减少动画',{exact:true}).check();
    assert.equal(await page.getByLabel('减少动画',{exact:true}).isChecked(),true);
  } finally {await page.close();}
});
test("desktop directory open reports failure and supports explicit retry", async () => {
  const page=await openPage('/settings',{'open-directory':{error:true}},{desktop:true});try {
    const button=page.getByRole('button',{name:'打开配置目录',exact:true});await button.click();
    await page.getByText(/未能打开配置目录/).waitFor();
    await page.evaluate(()=>{window.__fixtures['open-directory']={value:undefined};});await button.click();
    await page.getByText('已请求系统打开配置目录。',{exact:true}).waitFor();
    assert.equal(await page.getByText('synthetic-never-in-dom',{exact:true}).count(),0);
  } finally {await page.close();}
});
test("settings configuration retry recovers through the real bridge after invoke rejection", async () => {
  const page=await openPage('/settings',{desktop:{error:true}},{desktop:true});try {
    await page.getByText(/无法读取桌面配置/).waitFor();
    assert.equal(await page.getByRole('button',{name:'打开配置目录',exact:true}).count(),0);
    await page.evaluate(runtime=>{window.__fixtures.desktop={value:runtime};},runtime);
    await page.getByRole('button',{name:'重新读取桌面配置',exact:true}).click();
    await page.getByText(runtime.configFile,{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'打开配置目录',exact:true}).isEnabled(),true);
    assert.equal(await page.evaluate(()=>window.__calls.filter(c=>c.name==='desktop').length),2);
    assert.equal(await page.getByText(runtime.sessionToken,{exact:true}).count(),0);
  }finally{await page.close();}
});
test("source failure is UNKNOWN; retry GET yields a verified empty state", async () => {
  const page=await openPage('/integrations',{sources:{error:true}});try {
    await page.getByText('来源清单未核实',{exact:true}).waitFor();
    assert.equal(await page.getByText('当前工作空间还没有授权来源。',{exact:true}).count(),0);
    await page.evaluate(()=>{window.__fixtures.sources={value:[]};});
    await page.getByRole('button',{name:'重新读取来源',exact:true}).click();
    await page.getByText('当前工作空间还没有授权来源。',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>window.__calls.some(c=>['authorize','revoke','probe'].includes(c.name))),false);
  } finally {await page.close();}
});
test("integrations separates working model entry from optional contracts", async () => {
  const page=await openPage('/integrations');try {
    await page.getByRole('heading',{name:'数据来源与集成',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'进入流程',exact:true}).count(),0);
    const contracts=page.locator('details').filter({has:page.locator('summary',{hasText:'扩展合同目录'})});
    assert.equal(await contracts.getAttribute('open'),null);
    await page.getByRole('link',{name:'管理模型与 API',exact:true}).click();
    await page.getByRole('heading',{name:'destination /models',exact:true}).waitFor();
  } finally {await page.close();}
});
test("a source response arriving after disconnect cannot become a verified zero", async () => {
  const page=await openPage('/integrations',{sources:{hold:true,value:[]}});try {
    await page.waitForFunction(()=>Boolean(window.__held.sources));
    await page.evaluate(()=>window.__setProduct({...window.__product,connection:{api:'UNAVAILABLE'}}));
    await page.getByText('来源清单未核实',{exact:true}).waitFor();
    await page.evaluate(()=>window.__held.sources());
    assert.equal(await page.getByText('当前工作空间还没有授权来源。',{exact:true}).count(),0);
  } finally {await page.close();}
});
test("source registration requires an explicit attestation and preserves the exact adapter boundary", async () => {
  const page=await openPage('/integrations',{authorize:{value:source}});try {
    await page.getByText('当前工作空间还没有授权来源。',{exact:true}).waitFor();
    await page.getByText('登记受控发布目录',{exact:true}).click();
    await page.getByText(/此入口适配 Omni-AD/).waitFor();
    await page.getByLabel('显示名称',{exact:true}).fill(source.display_name);
    await page.getByLabel('服务端绝对目录',{exact:true}).fill('C:/Synthetic/omni-release');
    await page.getByLabel('发布归档 SHA-256',{exact:false}).fill('a'.repeat(64));
    await page.getByLabel('使用目的',{exact:true}).fill('仅用于合成集成测试验证');
    await page.getByLabel('权利依据',{exact:true}).fill('合成测试数据没有真实客户');
    const submit=page.getByRole('button',{name:'登记只读来源',exact:true});
    assert.equal(await submit.isDisabled(),true);
    await page.getByRole('checkbox',{name:/我确认有权/}).check();await submit.click();
    await page.getByText(source.display_name,{exact:true}).waitFor();
    const writes=await page.evaluate(()=>window.__calls.filter(c=>c.name==='authorize'));
    assert.equal(writes.length,1);assert.equal(writes[0].input.rootPath,'C:/Synthetic/omni-release');
    mkdirSync(path.join(root,'output/playwright/control-surfaces'),{recursive:true});
    await page.screenshot({path:path.join(root,'output/playwright/control-surfaces/source-registration-1440.png'),fullPage:true});
  }finally{await page.close();}
});
test("unknown registration blocks another write while explicit refresh only reconciles GET", async () => {
  const page=await openPage('/integrations',{authorize:{error:true}});try {
    await page.getByText('当前工作空间还没有授权来源。',{exact:true}).waitFor();
    await page.getByText('登记受控发布目录',{exact:true}).click();
    await page.getByLabel('显示名称',{exact:true}).fill(source.display_name);
    await page.getByLabel('服务端绝对目录',{exact:true}).fill('C:/Synthetic/omni-release');
    await page.getByLabel('发布归档 SHA-256',{exact:false}).fill('a'.repeat(64));
    await page.getByLabel('使用目的',{exact:true}).fill('仅用于合成集成测试验证');
    await page.getByLabel('权利依据',{exact:true}).fill('合成测试数据没有真实客户');
    await page.getByRole('checkbox',{name:/我确认有权/}).check();
    await page.getByRole('button',{name:'登记只读来源',exact:true}).click();
    await page.getByText(/登记结果未核实/).waitFor();
    await page.evaluate(source=>{window.__fixtures.sources={value:[source]};},source);
    // A read can safely show the result; it must never replay the previous POST.
    await page.getByRole('button',{name:'重新读取来源',exact:true}).click();
    assert.equal(await page.getByRole('button',{name:'登记只读来源',exact:true}).isDisabled(),true);
    assert.equal(await page.evaluate(()=>window.__calls.filter(c=>c.name==='authorize').length),1);
  }finally{await page.close();}
});
test("source revoke requires a reason and preserves the bound authorization digest", async () => {
  const event={event_id:'evt_test',sequence:2,event_type:'REVOKED',reason:'合成测试撤销授权',actor_id:user.user_id,event_sha256:'c'.repeat(64),fail_closed_task_ids:[]};
  const page=await openPage('/integrations',{sources:{value:[source]},revoke:{value:event}});try {
    await page.getByRole('button',{name:'撤销来源授权',exact:true}).click();
    const button=page.getByRole('button',{name:'永久撤销此授权',exact:true});assert.equal(await button.isDisabled(),true);
    await page.getByLabel('撤销原因',{exact:true}).fill('合成测试，撤销此目录授权');await button.click();
    await page.getByText('已撤销',{exact:true}).waitFor();
    const writes=await page.evaluate(()=>window.__calls.filter(c=>c.name==='revoke'));
    assert.equal(writes.length,1);assert.equal(writes[0].input.expectedLatestEventSha256,'b'.repeat(64));
  }finally{await page.close();}
});
test("Hosted remains optional and cannot probe until locally configured", async () => {
  const page=await openPage('/integrations');try {
    await page.getByText('扩展合同目录',{exact:true}).click();
    await page.getByRole('button',{name:'查看合同与状态 · AgentTeams v1.2.2',exact:true}).click();
    await page.getByText(/本地检查任务不依赖此连接/).waitFor();
    assert.equal(await page.getByRole('button',{name:'执行只读探测',exact:true}).isDisabled(),true);
    assert.equal(await page.evaluate(()=>window.__calls.some(c=>c.name==='probe')),false);
  }finally{await page.close();}
});
test("catalog search and contract selection are keyboard-operable", async () => {
  const page=await openPage('/integrations');try {
    const summary=page.getByText('扩展合同目录',{exact:true});await summary.focus();await page.keyboard.press('Enter');
    await page.getByRole('textbox',{name:'搜索扩展合同',exact:true}).fill('CVAT');
    const button=page.getByRole('button',{name:'查看合同与状态 · CVAT',exact:true});await button.focus();await page.keyboard.press('Enter');
    await page.getByRole('heading',{name:'CVAT',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:/查看合同与状态/}).count(),1);
    mkdirSync(path.join(root,'output/playwright/control-surfaces'),{recursive:true});
    await page.screenshot({path:path.join(root,'output/playwright/control-surfaces/contract-inspector-1440.png'),fullPage:true});
    await page.getByRole('textbox',{name:'搜索扩展合同',exact:true}).fill('does-not-exist');
    await page.getByText('没有匹配的合同，请调整搜索词。',{exact:true}).waitFor();
  }finally{await page.close();}
});
test("account replacement updates settings without leaving the previous actor", async () => {
  const page=await openPage();try {
    await page.getByText(user.user_id,{exact:true}).waitFor();
    await page.evaluate(user=>window.__identity.setIdentitySession({...user,user_id:'usr_second',display_name:'第二位测试员'},'synthetic-second-bearer-0123456789012345'),user);
    await page.getByText('usr_second',{exact:true}).waitFor();assert.equal(await page.getByText(user.user_id,{exact:true}).count(),0);
  }finally{await page.close();}
});
test("desktop control pages fit 1280/1440/1920 and provide screenshot evidence", async () => {
  mkdirSync(path.join(root,'output/playwright/control-surfaces'),{recursive:true});
  for(const width of [1280,1440,1920])for(const route of ['/settings','/integrations']){
    const page=await openPage(route,{}, {width});try {
      await page.waitForFunction(()=>document.fonts.status==='loaded');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
      await page.screenshot({path:path.join(root,`output/playwright/control-surfaces/${route.slice(1)}-${width}.png`),fullPage:true});
    }finally{await page.close();}
  }
});
