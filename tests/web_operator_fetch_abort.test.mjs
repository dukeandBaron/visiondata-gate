/** Real operatorFetch, isolated runtime and fetch doubles; no real accounts or backend. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';
const require = createRequire(new URL('../web/package.json', import.meta.url));
const { build } = await import(pathToFileURL(require.resolve('vite')).href);
const result = await build({ configFile: false, envDir: false, logLevel: 'error', define: { 'import.meta.env': '{}' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('../web/src/data/api.ts', import.meta.url)), name: 'Api', formats: ['iife'] } },
  plugins: [{ name: 'isolated-abort-runtime', enforce: 'pre', resolveId(id) { if (id === '@tauri-apps/api/core') return '\0test-invoke'; },
    load(id) { if (id === '\0test-invoke') return 'export const invoke=(...args)=>globalThis.__invoke(...args)'; } }],
});
const code = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk').code;
function runtime(fetcher) {
  const timers = new Set();
  const context = { Headers, AbortController, AbortSignal, DOMException,
    window: { __TAURI_INTERNALS__: {}, location: { origin: 'http://tauri.localhost' },
      setTimeout: (callback, ms) => { const timer = setTimeout(callback, ms); timers.add(timer); return timer; }, clearTimeout: timer => { clearTimeout(timer); timers.delete(timer); } },
    __invoke: async () => ({ apiBaseUrl: 'http://127.0.0.1:18080', sessionToken: 'synthetic-abort-token' }), fetch: fetcher };
  vm.runInNewContext(code, context); return { api: context.Api, timers };
}
test('caller cancellation reaches the real operatorFetch transport and releases timeout state', async () => {
  let received, ready; const dispatched = new Promise(resolve => { ready = resolve; });
  const { api, timers } = runtime(async (url, init) => { received = init; ready(); return new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
  }); });
  const controller = new AbortController(); const promise = api.operatorFetch('/v1/test', { signal: controller.signal, headers: { Accept: 'image/png' } }, 1000);
  await dispatched; controller.abort(); assert.equal(received.signal.aborted, true);
  await assert.rejects(promise, { code: 'REQUEST_TIMEOUT' }); assert.equal(timers.size, 0);
  assert.equal(received.headers.get('Accept'), 'image/png'); assert.equal(received.headers.get('X-VisionData-Desktop-Token'), 'synthetic-abort-token');
});
test('original timeout still aborts when a live caller signal is supplied, with no lingering timer', async () => {
  const { api, timers } = runtime(async (url, init) => new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('timed out', 'AbortError')), { once: true });
  }));
  await assert.rejects(api.operatorFetch('/v1/test', { signal: new AbortController().signal }, 5), { code: 'REQUEST_TIMEOUT' }); assert.equal(timers.size, 0);
});
test('successful reads install no caller listeners and release the original timeout', async () => {
  const controller = new AbortController(); let added = 0; const original = controller.signal.addEventListener.bind(controller.signal);
  controller.signal.addEventListener = (...args) => { added++; return original(...args); };
  const { api, timers } = runtime(async () => new Response('ok'));
  await api.operatorFetch('/v1/test', { signal: controller.signal }); assert.equal(added, 0); assert.equal(timers.size, 0);
});
