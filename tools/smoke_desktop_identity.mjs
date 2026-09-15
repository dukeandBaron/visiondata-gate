/** Verify a DevTools-enabled internal WebView; release installers use the UIA smoke. */
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const validationMode = 'DEVTOOLS_ENABLED_INTERNAL_ONLY';
assert.equal(
  process.env.VDG_EXPECT_DEVTOOLS_ENABLED,
  'true',
  'release builds disable DevTools; use smoke_desktop_identity_uia.ps1',
);

const [application, workRoot, mode = 'full'] = process.argv.slice(2);
assert.ok(application && path.isAbsolute(application) && existsSync(application));
assert.ok(
  workRoot && path.isAbsolute(workRoot) && !existsSync(workRoot),
  'use a new isolated output root',
);
assert.ok(['full', 'probe'].includes(mode), 'mode must be full or probe');

const playwrightModule = process.env.VDG_PLAYWRIGHT_MODULE;
assert.ok(
  playwrightModule && path.isAbsolute(playwrightModule) && existsSync(playwrightModule),
  'VDG_PLAYWRIGHT_MODULE must name an existing absolute playwright module',
);
const { chromium } = await import(pathToFileURL(playwrightModule).href);

mkdirSync(workRoot, { recursive: true });
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const server = createServer();
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
await new Promise(resolve => server.close(resolve));

const password = randomBytes(24).toString('base64url');
const environment = Object.fromEntries(
  Object.entries(process.env).filter(([key]) => !key.startsWith('VISIONDATA_')),
);
const requests = [];
const failures = [];
const actions = [];
let child;
let browser;
let currentPage;

async function start() {
  child = spawn(application, [], {
    cwd: path.dirname(application),
    windowsHide: true,
    stdio: 'ignore',
    env: {
      ...environment,
      LOCALAPPDATA: path.join(workRoot, 'local'),
      APPDATA: path.join(workRoot, 'roaming'),
      USERPROFILE: path.join(workRoot, 'profile'),
      TEMP: path.join(workRoot, 'temp'),
      TMP: path.join(workRoot, 'temp'),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:
        `--remote-debugging-address=127.0.0.1 --remote-debugging-port=${port}`,
      WEBVIEW2_USER_DATA_FOLDER: path.join(workRoot, 'webview'),
    },
  });
  for (let attempt = 0; attempt < 120; attempt += 1) {
    assert.equal(child.exitCode, null, 'desktop exited before WebView readiness');
    try {
      browser = await chromium.connectOverCDP(
        `http://127.0.0.1:${port}`,
        { timeout: 1000 },
      );
      break;
    } catch {
      await pause(500);
    }
  }
  assert.ok(browser, 'desktop CDP unavailable');
  const page = browser.contexts()[0].pages()[0];
  assert.ok(page, 'desktop WebView page unavailable');
  currentPage = page;
  page.setDefaultTimeout(20_000);
  page.on('response', response => {
    const url = new URL(response.url());
    if (url.pathname.startsWith('/v1/identity')) {
      requests.push({
        path: url.pathname,
        method: response.request().method(),
        status: response.status(),
      });
    }
  });
  page.on('requestfailed', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/v1/')) {
      failures.push({ path: url.pathname, error: request.failure()?.errorText });
    }
  });
  return page;
}

async function stop({ requireGraceful = true } = {}) {
  if (!child || child.exitCode !== null) return;
  const closer = spawn(
    'powershell.exe',
    [
      '-NoProfile',
      '-Command',
      `(Get-Process -Id ${child.pid}).CloseMainWindow() | Out-Null`,
    ],
    { windowsHide: true, stdio: 'ignore' },
  );
  await new Promise(resolve => closer.once('exit', resolve));
  for (let attempt = 0; attempt < 60 && child.exitCode === null; attempt += 1) {
    await pause(500);
  }
  const graceful = child.exitCode === 0;
  if (child.exitCode === null) {
    child.kill();
    for (let attempt = 0; attempt < 20 && child.exitCode === null; attempt += 1) {
      await pause(250);
    }
  }
  browser = undefined;
  if (requireGraceful) assert.ok(graceful, 'desktop must exit gracefully');
}

async function login(page, name) {
  await page.getByLabel('登录名', { exact: true }).fill(name);
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.locator('.linear-sidebar').waitFor();
  await page.locator('a.linear-user').click();
  await page.getByTestId('identity-account-page').waitFor();
}

try {
  let page = await start();
  if (mode === 'probe') {
    await page.getByRole('heading', { name: '暂时无法确认账户状态' }).waitFor();
    await page.screenshot({ path: path.join(workRoot, 'blocked.png') });
    actions.push('REPRODUCED_ACCOUNT_STATUS_BLOCK');
  } else {
    await page.getByRole('heading', { name: '创建首个管理员' }).waitFor();
    await page.getByLabel('登录名', { exact: true }).fill('desktop-smoke-admin');
    await page.getByLabel('显示名称', { exact: true }).fill('安装版验证管理员');
    await page.getByLabel('密码', { exact: true }).fill(password);
    await page.getByLabel('再次输入密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '创建管理员并登录' }).click();
    await page.locator('.linear-sidebar').waitFor();
    actions.push('SETUP_AND_LOGIN');

    await page.locator('a.linear-user').click();
    await page.getByTestId('identity-account-page').waitFor();
    await page.screenshot({ path: path.join(workRoot, 'authenticated.png') });
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.getByLabel('登录名', { exact: true }).fill('desktop-smoke-admin');
    await page.getByLabel('密码', { exact: true }).fill('wrong-password-for-smoke');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '登录信息无效' }).waitFor();
    assert.equal(
      await page.getByRole('button', { name: '登录', exact: true }).isEnabled(),
      true,
    );
    actions.push('INVALID_PASSWORD_RECOVERABLE');

    await page.getByRole('button', { name: '没有账户？提交注册申请' }).click();
    await page.getByLabel('登录名', { exact: true }).fill('desktop-smoke-member');
    await page.getByLabel('显示名称', { exact: true }).fill('安装版验证成员');
    await page.getByLabel('密码', { exact: true }).fill(password);
    await page.getByLabel('再次输入密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '提交注册申请', exact: true }).click();
    await page.getByText(
      '注册申请已登记，当前状态为待管理员审批。尚未登录，也没有获得工作区权限。',
      { exact: true },
    ).waitFor();
    actions.push('REGISTER_PENDING');

    await login(page, 'desktop-smoke-admin');
    await page.getByRole('button', { name: '批准注册', exact: true }).click();
    await page.getByRole('button', { name: '确认批准注册', exact: true }).click();
    await page.getByRole('button', { name: '确认批准注册', exact: true })
      .waitFor({ state: 'hidden' });
    actions.push('ADMIN_APPROVAL');
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await login(page, 'desktop-smoke-member');
    actions.push('MEMBER_LOGIN');
    await page.screenshot({ path: path.join(workRoot, 'member.png') });

    await stop();
    page = await start();
    await page.getByRole('heading', { name: '登录工作台', exact: true }).waitFor();
    await login(page, 'desktop-smoke-member');
    actions.push('RESTART_AND_LOGIN');
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.getByRole('heading', { name: '登录工作台', exact: true }).waitFor();
    actions.push('LOGOUT');
  }
  await stop();
  const status = mode === 'probe'
    ? 'REPRODUCED_ACCOUNT_STATUS_BLOCK'
    : 'PASS_REAL_DESKTOP_IDENTITY';
  writeFileSync(
    path.join(workRoot, 'IDENTITY_DESKTOP_SMOKE.json'),
    JSON.stringify({
      status,
      validation_mode: validationMode,
      application_sha256: createHash('sha256')
        .update(readFileSync(application))
        .digest('hex'),
      scope: 'REAL_WEBVIEW_IPC_SPRING_FASTAPI_ISOLATED_DATA',
      actions,
      requests,
      failures,
      clean_machine_validation: 'NOT_RUN',
      production_release_allowed: false,
    }, null, 2),
  );
  console.log(JSON.stringify({ status, actions, requests, failures }));
} catch (error) {
  await currentPage?.screenshot({ path: path.join(workRoot, 'failure.png') })
    .catch(() => {});
  writeFileSync(
    path.join(workRoot, 'FAILURE.json'),
    JSON.stringify({
      status: 'FAIL',
      validation_mode: validationMode,
      name: error?.name || 'Error',
      message: String(error?.message || error),
      actions,
      requests,
      failures,
    }, null, 2),
  );
  await stop({ requireGraceful: false });
  throw error;
}
