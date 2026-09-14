/** Real bridge module, with only Tauri invoke replaced by a deterministic transport. */
import assert from 'node:assert/strict';
import { before, test } from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const root = fileURLToPath(new URL('..', import.meta.url));
const webRoot = path.join(root, 'web');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build } = await import(pathToFileURL(require.resolve('vite')).href);
let code;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: 'error',
    build: { write: false, minify: false, lib: { entry: path.join(webRoot, 'src/platform/bridge.ts'), name: 'DesktopBridge', formats: ['iife'] } },
    plugins: [{ name: 'isolated-tauri-invoke', enforce: 'pre', resolveId(id) {
      if (id === '@tauri-apps/api/core') return '\0synthetic-invoke';
    }, load(id) {
      if (id === '\0synthetic-invoke') return 'export const invoke=(...args)=>globalThis.__invoke(...args);';
    } }],
  });
  code = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk').code;
});
function bridge(invoke, desktop = true) {
  const context = { window: desktop ? { __TAURI_INTERNALS__: {} } : {}, navigator: { platform: 'Win32' }, __invoke: invoke };
  vm.runInNewContext(code, context);
  return context.DesktopBridge;
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((success, failure) => { resolve = success; reject = failure; });
  return { promise, resolve, reject };
}
const config = { apiBaseUrl: 'http://127.0.0.1:1234', sessionToken: 'synthetic-secret', dataRoot: 'C:/Synthetic/data', configFile: 'C:/Synthetic/config.env', sampleDataRoot: 'C:/Synthetic/sample' };

test('a rejected desktop config read is not cached; explicit retry can succeed', async () => {
  let calls = 0;
  const api = bridge(command => { assert.equal(command, 'desktop_runtime_config'); calls += 1; return calls === 1 ? Promise.reject(new Error('synthetic first failure')) : Promise.resolve(config); });
  const first = api.resolveDesktopRuntimeConfig();
  await assert.rejects(first, /synthetic first failure/);
  const retry = api.resolveDesktopRuntimeConfig();
  assert.notEqual(retry, first);
  assert.equal(await retry, config);
  assert.equal(calls, 2);
});
test('concurrent reads share one pending request and the successful result stays cached', async () => {
  const pending = deferred(); let calls = 0;
  const api = bridge(() => { calls += 1; return pending.promise; });
  const first = api.resolveDesktopRuntimeConfig(); const second = api.resolveDesktopRuntimeConfig();
  assert.equal(first, second);
  pending.resolve(config);
  assert.equal(await first, config); assert.equal(await second, config);
  assert.equal(api.resolveDesktopRuntimeConfig(), first);
  assert.equal(calls, 1);
});
test('all callers see the failed attempt, then concurrent retries share a fresh request', async () => {
  const firstTransport = deferred(); const retryTransport = deferred(); let calls = 0;
  const api = bridge(() => (++calls === 1 ? firstTransport.promise : retryTransport.promise));
  const first = api.resolveDesktopRuntimeConfig(); const concurrent = api.resolveDesktopRuntimeConfig();
  const observed = Promise.allSettled([first, concurrent]); firstTransport.reject(new Error('synthetic unavailable'));
  assert.deepEqual((await observed).map(value => value.status), ['rejected', 'rejected']);
  const retry = api.resolveDesktopRuntimeConfig(); const retryConcurrent = api.resolveDesktopRuntimeConfig();
  assert.equal(retry, retryConcurrent); assert.notEqual(retry, first);
  retryTransport.resolve(config); assert.equal(await retry, config); assert.equal(calls, 2);
});
test('browser mode never invokes a desktop command', async () => {
  let calls = 0; const api = bridge(() => { calls += 1; }, false);
  assert.equal(await api.resolveDesktopRuntimeConfig(), undefined); assert.equal(calls, 0);
});
