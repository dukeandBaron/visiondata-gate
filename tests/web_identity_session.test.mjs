import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  clearIdentitySession, getIdentityActorId, getIdentitySessionHeaders,
  getIdentitySessionSnapshot, setIdentitySession, subscribeIdentitySession,
} from "../web/src/identitySession.ts";

const user = { user_id: "usr_alice", display_name: "Alice", login_name: "alice", email: null,
  created_at: "2026-09-12T01:00:00Z", platform_role: "USER", status: "ACTIVE" };
const token = "test-only-user-bearer-01234567890123456789";

test("session credentials start empty and cannot promote pending accounts", () => {
  clearIdentitySession();
  assert.equal(getIdentityActorId(), undefined);
  assert.deepEqual(getIdentitySessionHeaders(), {});
  assert.throws(() => setIdentitySession({ ...user, status: "PENDING" }, token));
  assert.throws(() => setIdentitySession({ ...user, platform_role: "OWNER" }, token));
  assert.throws(() => setIdentitySession(user, "short"));
  assert.deepEqual(getIdentitySessionHeaders(), {});
});

test("session changes are reactive, copied, immutable and contain no bearer in snapshots", () => {
  clearIdentitySession();
  const previous = getIdentitySessionSnapshot();
  let notifications = 0;
  const unsubscribe = subscribeIdentitySession(() => { notifications += 1; });
  const input = { ...user, password: "must-not-enter-public-state" };
  setIdentitySession(input, token);
  input.display_name = "Mutated";
  const current = getIdentitySessionSnapshot();
  assert.equal(current.generation, previous.generation + 1);
  assert.equal(current.user.display_name, "Alice");
  assert.equal(Object.isFrozen(current.user), true);
  assert.equal(getIdentityActorId(), "usr_alice");
  assert.deepEqual(getIdentitySessionHeaders(), { Authorization: `Bearer ${token}` });
  assert.equal("password" in current.user, false);
  assert.equal(JSON.stringify(current).includes(token), false);
  const headers = getIdentitySessionHeaders();
  headers.Authorization = "tampered";
  assert.equal(getIdentitySessionHeaders().Authorization, `Bearer ${token}`);
  clearIdentitySession();
  assert.equal(notifications, 2);
  assert.equal(getIdentityActorId(), undefined);
  assert.deepEqual(getIdentitySessionHeaders(), {});
  assert.equal(getIdentitySessionSnapshot().generation, previous.generation + 2);
  unsubscribe();
  clearIdentitySession();
  assert.equal(notifications, 2);
});

test("identity credentials have no Web Storage or DOM persistence path", async () => {
  const source = await readFile(new URL("../web/src/identitySession.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB|document\.|window\.|console\./);
  assert.doesNotMatch(source, /X-Actor-User-Id/);
});
