/** User bearer credentials live only in this module's memory, never browser storage. */
export interface IdentityPublicUser {
  user_id: string;
  display_name: string;
  login_name: string;
  email: string | null;
  created_at: string;
  platform_role: "ADMIN" | "USER";
  status: "PENDING" | "ACTIVE" | "DISABLED";
}

export interface IdentitySessionSnapshot {
  readonly user: Readonly<IdentityPublicUser> | undefined;
  readonly generation: number;
}

let bearer: string | undefined;
let snapshot: IdentitySessionSnapshot = Object.freeze({ user: undefined, generation: 0 });
const listeners = new Set<() => void>();

export function getIdentitySessionSnapshot(): IdentitySessionSnapshot {
  return snapshot;
}

export function getIdentitySessionHeaders(): Record<string, string> {
  return bearer ? { Authorization: `Bearer ${bearer}` } : {};
}

export function getIdentityActorId(): string | undefined {
  return snapshot.user?.user_id;
}

export function subscribeIdentitySession(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function publish(user: Readonly<IdentityPublicUser> | undefined): void {
  snapshot = Object.freeze({ user, generation: snapshot.generation + 1 });
  for (const listener of listeners) listener();
}

export function setIdentitySession(publicUser: IdentityPublicUser, token: string): void {
  if (!publicUser || typeof publicUser.user_id !== "string" || !publicUser.user_id.trim()
    || typeof publicUser.display_name !== "string" || !publicUser.display_name.trim()
    || typeof publicUser.login_name !== "string" || !/^[a-z0-9][a-z0-9._-]{2,63}$/.test(publicUser.login_name)
    || !(publicUser.email === null || typeof publicUser.email === "string")
    || typeof publicUser.created_at !== "string" || !Number.isFinite(Date.parse(publicUser.created_at))
    || !["ADMIN", "USER"].includes(publicUser.platform_role) || publicUser.status !== "ACTIVE"
    || typeof token !== "string" || token.length < 32 || token.length > 512 || /\s/.test(token)) {
    throw new Error("身份会话合同无效，未建立登录状态。");
  }
  // Copy only public allowlisted fields; a caller cannot smuggle secrets into React state.
  const user = Object.freeze({ user_id: publicUser.user_id, display_name: publicUser.display_name,
    login_name: publicUser.login_name, email: publicUser.email, created_at: publicUser.created_at,
    platform_role: publicUser.platform_role, status: publicUser.status });
  bearer = token;
  publish(user);
}

export function clearIdentitySession(): void {
  bearer = undefined;
  publish(undefined);
}
