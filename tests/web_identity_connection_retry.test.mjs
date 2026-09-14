import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const require = createRequire(new URL('../web/package.json', import.meta.url));
const { build } = await import(pathToFileURL(require.resolve('vite')).href);
const result = await build({ configFile: false, envDir: false, logLevel: 'error',
  define: { 'import.meta.env': '{}' },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('../web/src/data/identityApi.ts', import.meta.url)),
    name: 'IdentityApi', formats: ['iife'],
  } },
  plugins: [{ name: 'test-desktop-transport', enforce: 'pre',
    resolveId(id) { if (id === '@tauri-apps/api/core') return '\0test-invoke'; },
    load(id) { if (id === '\0test-invoke') return 'export const invoke=(...args)=>globalThis.__invoke(...args)'; },
  }],
});
const code = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk').code;

test('identity refresh recovers after desktop bootstrap fails without sending a write', async () => {
  let invocations = 0; const requests = [];
  const context = { Headers, AbortController, DOMException,
    window: { __TAURI_INTERNALS__: {}, location: { origin: 'http://tauri.localhost' }, setTimeout, clearTimeout },
    __invoke: async () => {
      if (++invocations === 1) throw new Error('startup not ready');
      return { apiBaseUrl: 'http://127.0.0.1:18080', sessionToken: 'synthetic-startup-token' };
    },
    fetch: async (url, init) => {
      requests.push({url, method: init.method});
      return new Response(JSON.stringify({setup_required: true, identity_required: false,
        registration_policy: 'ADMIN_APPROVAL', authentication_mode: 'SETUP_REQUIRED', startup_capability_required: true}));
    },
  };
  vm.runInNewContext(code, context);
  await assert.rejects(context.IdentityApi.getIdentityStatus(), /startup not ready/);
  assert.equal((await context.IdentityApi.getIdentityStatus()).setup_required, true);
  assert.equal(invocations, 2);
  assert.deepEqual(requests, [{url: 'http://127.0.0.1:18080/v1/identity/status', method: 'GET'}]);
});
